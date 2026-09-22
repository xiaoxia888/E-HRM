from __future__ import annotations

from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import threading
import time
from typing import Any
from uuid import uuid4

from ehrm.core.exceptions import TaskCancelledError


class TaskKind(StrEnum):
    JSHRSS_BROWSER = "jshrss_browser"
    ERP_BROWSER = "erp_browser"
    API_QUERY = "api_query"
    ERP_WRITE = "erp_write"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    task_id: str
    title: str
    operation: str
    kind: TaskKind
    status: TaskStatus
    resource_label: str
    queue_position: int
    message: str
    progress_current: int
    progress_total: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    result: object | None
    error: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class TaskContext:
    def __init__(
        self,
        task_id: str,
        cancel_event: threading.Event,
        progress_callback: Callable[[str, int | None, int | None], None],
    ) -> None:
        self.task_id = task_id
        self._cancel_event = cancel_event
        self._progress_callback = progress_callback

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise TaskCancelledError("任务已由用户停止")

    def report(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        self.raise_if_cancelled()
        self._progress_callback(message, current, total)


TaskRunner = Callable[[TaskContext], object | None]


@dataclass(slots=True)
class _TaskRecord:
    task_id: str
    title: str
    operation: str
    kind: TaskKind
    resource_key: str
    resource_label: str
    runner: TaskRunner
    status: TaskStatus = TaskStatus.QUEUED
    message: str = "任务已创建，正在等待调度"
    progress_current: int = 0
    progress_total: int = 1
    result: object | None = None
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)


class TaskCoordinator:
    """Single-server coordinator with resource-keyed serial queues.

    Browser jobs are serialized by JSHRSS account. ERP mutations are
    serialized by account/unit. API-only queries have no resource lock and are
    submitted immediately to the shared executor.
    """

    def __init__(self, *, max_workers: int = 8, history_limit: int = 500) -> None:
        if max_workers < 1:
            raise ValueError("max_workers 必须大于 0")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="ehrm-web-task",
        )
        self._history_limit = max(history_limit, 10)
        self._tasks: dict[str, _TaskRecord] = {}
        self._order: deque[str] = deque()
        self._resource_queues: dict[str, deque[str]] = {}
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._revision = 0
        self._closed = False

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def submit(
        self,
        *,
        title: str,
        operation: str,
        kind: TaskKind,
        runner: TaskRunner,
        resource_key: str = "",
        resource_label: str = "",
    ) -> TaskSnapshot:
        normalized_title = title.strip()
        normalized_operation = operation.strip()
        normalized_key = resource_key.strip()
        if not normalized_title or not normalized_operation:
            raise ValueError("任务标题和操作类型不能为空")
        if kind in {
            TaskKind.JSHRSS_BROWSER,
            TaskKind.ERP_BROWSER,
            TaskKind.ERP_WRITE,
        } and not normalized_key:
            raise ValueError("浏览器任务和 ERP 写入任务必须指定资源账号")

        with self._lock:
            if self._closed:
                raise RuntimeError("任务协调器已停止")
            task_id = uuid4().hex
            record = _TaskRecord(
                task_id=task_id,
                title=normalized_title,
                operation=normalized_operation,
                kind=kind,
                resource_key=normalized_key,
                resource_label=resource_label.strip() or "未命名资源",
                runner=runner,
            )
            self._tasks[task_id] = record
            self._order.appendleft(task_id)
            resource_token = self._resource_token(record)
            if resource_token is None:
                record.message = "查询任务已创建，将立即并行执行"
                self._schedule(record)
            else:
                queue = self._resource_queues.setdefault(resource_token, deque())
                queue.append(task_id)
                if len(queue) == 1:
                    record.message = "任务资源已分配，正在启动"
                    self._schedule(record)
                else:
                    record.message = self._queued_message(record, len(queue) - 1)
            self._trim_history_locked()
            self._notify_locked()
            return self._snapshot_locked(record)

    def get(self, task_id: str) -> TaskSnapshot | None:
        with self._lock:
            record = self._tasks.get(task_id)
            return self._snapshot_locked(record) if record is not None else None

    def list(self, *, limit: int = 100) -> tuple[TaskSnapshot, ...]:
        with self._lock:
            task_ids = list(self._order)[: max(1, min(limit, self._history_limit))]
            return tuple(
                self._snapshot_locked(self._tasks[task_id])
                for task_id in task_ids
                if task_id in self._tasks
            )

    def cancel(self, task_id: str) -> TaskSnapshot | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            if record.status.terminal:
                return self._snapshot_locked(record)
            record.cancel_event.set()
            if record.status is TaskStatus.QUEUED:
                token = self._resource_token(record)
                if token is not None:
                    queue = self._resource_queues.get(token)
                    if queue is not None and task_id in queue:
                        was_first = queue[0] == task_id
                        queue.remove(task_id)
                        if not queue:
                            self._resource_queues.pop(token, None)
                        elif was_first:
                            self._schedule(self._tasks[queue[0]])
                record.status = TaskStatus.CANCELLED
                record.message = "任务已从队列中取消，不会执行任何业务操作"
                record.finished_at = datetime.now(UTC)
            elif record.status is TaskStatus.RUNNING:
                record.status = TaskStatus.CANCELLING
                record.message = "已收到停止请求，正在安全结束当前步骤，请稍候"
            self._notify_locked()
            return self._snapshot_locked(record)

    def wait_for_change(self, revision: int, *, timeout: float = 15.0) -> int:
        with self._changed:
            self._changed.wait_for(
                lambda: self._revision != revision or self._closed,
                timeout=max(timeout, 0.0),
            )
            return self._revision

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for record in self._tasks.values():
                if not record.status.terminal:
                    record.cancel_event.set()
            self._notify_locked()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _schedule(self, record: _TaskRecord) -> None:
        self._executor.submit(self._execute, record.task_id)

    def _execute(self, task_id: str) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None or record.status is TaskStatus.CANCELLED:
                return
            record.status = TaskStatus.RUNNING
            record.started_at = datetime.now(UTC)
            record.message = self._running_message(record)
            self._notify_locked()

        context = TaskContext(
            task_id,
            record.cancel_event,
            lambda message, current, total: self._report_progress(
                task_id,
                message,
                current,
                total,
            ),
        )
        try:
            context.raise_if_cancelled()
            result = record.runner(context)
            context.raise_if_cancelled()
        except TaskCancelledError:
            with self._lock:
                record.status = TaskStatus.CANCELLED
                record.message = "任务已安全停止，未继续执行后续步骤"
                record.finished_at = datetime.now(UTC)
                self._notify_locked()
        except Exception as exc:
            with self._lock:
                record.status = TaskStatus.FAILED
                message = str(getattr(exc, "message", "") or str(exc)).strip()
                details = str(getattr(exc, "details", "") or "").strip()
                record.error = message or type(exc).__name__
                if details and details != record.error:
                    record.error += f"\n{details}"
                record.message = "任务执行失败，请查看错误信息后重试"
                record.finished_at = datetime.now(UTC)
                self._notify_locked()
        else:
            with self._lock:
                record.status = TaskStatus.SUCCEEDED
                record.result = result
                record.progress_current = max(
                    record.progress_current,
                    record.progress_total,
                )
                record.message = "任务已完成，可以查看或下载处理结果"
                record.finished_at = datetime.now(UTC)
                self._notify_locked()
        finally:
            self._release_resource(record)

    def _report_progress(
        self,
        task_id: str,
        message: str,
        current: int | None,
        total: int | None,
    ) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None or record.status.terminal:
                return
            normalized = message.strip()
            if normalized:
                record.message = normalized
            if total is not None:
                record.progress_total = max(int(total), 1)
            if current is not None:
                record.progress_current = max(
                    0,
                    min(int(current), record.progress_total),
                )
            self._notify_locked()

    def _release_resource(self, record: _TaskRecord) -> None:
        token = self._resource_token(record)
        if token is None:
            return
        with self._lock:
            queue = self._resource_queues.get(token)
            if queue is None:
                return
            if record.task_id in queue:
                queue.remove(record.task_id)
            if not queue:
                self._resource_queues.pop(token, None)
            else:
                next_record = self._tasks[queue[0]]
                next_record.message = "前序任务已结束，正在启动您的任务"
                self._schedule(next_record)
            self._notify_locked()

    def _snapshot_locked(self, record: _TaskRecord) -> TaskSnapshot:
        queue_position = 0
        if record.status is TaskStatus.QUEUED:
            token = self._resource_token(record)
            queue = self._resource_queues.get(token or "")
            if queue is not None and record.task_id in queue:
                queue_position = queue.index(record.task_id)
                if queue_position > 0:
                    record.message = self._queued_message(record, queue_position)
        return TaskSnapshot(
            task_id=record.task_id,
            title=record.title,
            operation=record.operation,
            kind=record.kind,
            status=record.status,
            resource_label=record.resource_label,
            queue_position=queue_position,
            message=record.message,
            progress_current=record.progress_current,
            progress_total=record.progress_total,
            created_at=record.created_at.isoformat(),
            started_at=record.started_at.isoformat() if record.started_at else None,
            finished_at=record.finished_at.isoformat() if record.finished_at else None,
            result=record.result,
            error=record.error,
        )

    @staticmethod
    def _resource_token(record: _TaskRecord) -> str | None:
        if record.kind is TaskKind.API_QUERY:
            return None
        return f"{record.kind.value}:{record.resource_key}"

    @staticmethod
    def _queued_message(record: _TaskRecord, ahead: int) -> str:
        if record.kind is TaskKind.JSHRSS_BROWSER:
            return (
                f"同一智慧人社账号“{record.resource_label}”正在处理其他任务，"
                f"已为您安全排队，前方还有 {ahead} 个任务；其他账号不受影响。"
            )
        if record.kind is TaskKind.ERP_BROWSER:
            return (
                f"同一 ERP 账号“{record.resource_label}”正在获取其他申请，"
                f"已为您安全排队，前方还有 {ahead} 个任务；其他账号不受影响。"
            )
        return (
            f"同一 ERP 账号或单位“{record.resource_label}”正在执行写入，"
            f"已为您安全排队，前方还有 {ahead} 个任务；普通查询不受影响。"
        )

    @staticmethod
    def _running_message(record: _TaskRecord) -> str:
        if record.kind is TaskKind.JSHRSS_BROWSER:
            return (
                f"正在使用智慧人社账号“{record.resource_label}”执行任务。"
                "您可以离开当前页面，任务进度会持续保存。"
            )
        if record.kind is TaskKind.ERP_BROWSER:
            return (
                f"正在使用 ERP 账号“{record.resource_label}”获取并解析申请信息。"
                "您可以留在当前页面查看进度，也可以前往任务中心。"
            )
        if record.kind is TaskKind.ERP_WRITE:
            return (
                f"正在向 ERP 账号或单位“{record.resource_label}”写入数据，"
                "请勿重复发起相同任务。"
            )
        return "正在并行查询数据，不会占用浏览器自动化队列"

    def _trim_history_locked(self) -> None:
        if len(self._order) <= self._history_limit:
            return
        for task_id in list(self._order)[self._history_limit :]:
            record = self._tasks.get(task_id)
            if record is not None and record.status.terminal:
                self._order.remove(task_id)
                self._tasks.pop(task_id, None)

    def _notify_locked(self) -> None:
        self._revision += 1
        self._changed.notify_all()


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 2.0,
    interval: float = 0.01,
) -> bool:
    """Small deterministic helper used by coordinator tests and diagnostics."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
