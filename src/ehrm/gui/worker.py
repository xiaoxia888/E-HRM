from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event, Lock

from PySide6.QtCore import QThread, Signal

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import TaskCancelledError
from ehrm.core.settings import AppSettings
from ehrm.modules.erp.batch_service import ErpBatchUploadService
from ehrm.modules.rights_statement.excel_models import ExcelTaskRequest
from ehrm.modules.rights_statement.excel_service import ExcelRightsStatementService
from ehrm.workbench import DesktopWorkbench


class AutomationWorker(QThread):
    """Runs every persistent Playwright call in one Python thread context.

    Playwright's synchronous API uses greenlets internally. Keeping a browser
    alive across separate QObject queued-slot callbacks can resume those
    greenlets from different Python contexts and crash the interpreter. This
    thread enters ``run`` once and consumes all desktop tasks from a queue, so
    browser creation, repeated jobs and shutdown share one execution context.
    """

    status_changed = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    _STOP = object()

    def __init__(self, settings: AppSettings, logger: logging.Logger) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._requests: Queue[ExcelTaskRequest | object] = Queue()
        self._state_lock = Lock()
        self._accepting = True
        self._task_active = False
        self._cancel_requested = Event()

    def submit(self, request: ExcelTaskRequest) -> bool:
        """Queues one request without invoking Playwright on the GUI thread."""
        with self._state_lock:
            if not self._accepting:
                return False
            if self._task_active:
                return False
            self._task_active = True
            self._cancel_requested.clear()
            self._requests.put(request)
            return True

    def cancel_current(self) -> bool:
        """Requests cooperative cancellation at the next safe checkpoint."""
        with self._state_lock:
            if not self._task_active:
                return False
            self._cancel_requested.set()
            return True

    def shutdown(self) -> None:
        """Stops after the active request; the GUI prevents closing mid-task."""
        with self._state_lock:
            if not self._accepting:
                return
            self._accepting = False
            self._requests.put(self._STOP)

    def run(self) -> None:
        workbench: DesktopWorkbench | None = None
        try:
            while True:
                request = self._requests.get()
                if request is self._STOP:
                    break
                try:
                    if workbench is None:
                        self.status_changed.emit("正在初始化权益单打印后端")
                        workbench = DesktopWorkbench(
                            self._settings,
                            self._logger,
                            self.status_changed.emit,
                            self._cancel_requested.is_set,
                        )
                        workbench.start()
                    self.status_changed.emit("正在查询并生成权益单 PDF")
                    result = workbench.run(request)
                    if getattr(request, "upload_to_erp", False) and not self._cancel_requested.is_set():
                        # The rights-site browser remains alive on this QThread.
                        # ERP owns another sync Playwright instance, so it must
                        # run in its own Python thread to avoid greenlet crashes.
                        with ThreadPoolExecutor(
                            max_workers=1,
                            thread_name_prefix="ehrm-erp-upload",
                        ) as executor:
                            result = executor.submit(
                                self._upload_to_erp,
                                request,
                                result,
                            ).result()
                    self._logger.info("自动化任务已完成，正在通知桌面界面")
                    self.completed.emit(result)
                except TaskCancelledError:
                    self._logger.info("任务在登录或页面恢复阶段被用户停止")
                    result = ExcelRightsStatementService(
                        self._settings,
                        self._logger,
                    ).cancelled_result(
                        list(request.groups),
                        request.mode,
                        request.output_dir,
                        request.source_excel,
                    )
                    self.completed.emit(result)
                except Exception as exc:
                    self._logger.exception("桌面端自动化任务失败")
                    code = getattr(exc, "code", "UNEXPECTED_ERROR")
                    message = getattr(exc, "message", str(exc))
                    summary = display_message(code, message)
                    details = getattr(exc, "details", None)
                    visible = summary
                    if message and message != summary:
                        visible += f"\n{message}"
                    if details and details not in {summary, message}:
                        visible += f"\n{details}"
                    self.failed.emit(visible)
                    if workbench is not None:
                        try:
                            workbench.stop()
                        except Exception:
                            self._logger.exception("重置异常工作台失败")
                        workbench = None
                finally:
                    with self._state_lock:
                        self._task_active = False
                    self._cancel_requested.clear()
        finally:
            with self._state_lock:
                self._accepting = False
            if workbench is not None:
                try:
                    workbench.stop()
                except Exception:
                    self._logger.exception("关闭桌面工作台浏览器失败")

    def _upload_to_erp(self, request: ExcelTaskRequest, result):
        items = ErpBatchUploadService(
            self._settings,
            self._logger,
            self.status_changed.emit,
            self._cancel_requested.is_set,
        ).execute(request, result)
        return ExcelRightsStatementService(
            self._settings,
            self._logger,
        ).refresh_artifacts(
            result,
            request.source_excel,
            request.output_dir,
            items,
        )
