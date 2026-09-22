from __future__ import annotations

from threading import Event, Lock

from ehrm.web.tasks import (
    TaskCoordinator,
    TaskKind,
    TaskStatus,
    wait_until,
)


def test_same_jshrss_account_runs_serially_with_friendly_queue_message() -> None:
    coordinator = TaskCoordinator(max_workers=4)
    release_first = Event()
    first_started = Event()
    second_started = Event()

    def first(context):
        first_started.set()
        while not release_first.wait(0.01):
            context.raise_if_cancelled()
        return {"row_count": 1}

    def second(_context):
        second_started.set()
        return {"row_count": 2}

    try:
        first_task = coordinator.submit(
            title="人员退保",
            operation="termination.prepare",
            kind=TaskKind.JSHRSS_BROWSER,
            resource_key="account-25",
            resource_label="南京单位账号",
            runner=first,
        )
        assert first_started.wait(1)
        second_task = coordinator.submit(
            title="人员参保",
            operation="enrollment.prepare",
            kind=TaskKind.JSHRSS_BROWSER,
            resource_key="account-25",
            resource_label="南京单位账号",
            runner=second,
        )

        queued = coordinator.get(second_task.task_id)
        assert queued is not None
        assert queued.status is TaskStatus.QUEUED
        assert queued.queue_position == 1
        assert "已为您安全排队" in queued.message
        assert "其他账号不受影响" in queued.message
        assert not second_started.wait(0.1)

        release_first.set()
        assert wait_until(
            lambda: coordinator.get(first_task.task_id).status
            is TaskStatus.SUCCEEDED
        )
        assert second_started.wait(1)
        assert wait_until(
            lambda: coordinator.get(second_task.task_id).status
            is TaskStatus.SUCCEEDED
        )
    finally:
        release_first.set()
        coordinator.close()


def test_different_jshrss_accounts_can_run_in_parallel() -> None:
    coordinator = TaskCoordinator(max_workers=4)
    both_started = Event()
    release = Event()
    lock = Lock()
    active = 0
    peak = 0

    def runner(context):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                both_started.set()
        while not release.wait(0.01):
            context.raise_if_cancelled()
        with lock:
            active -= 1

    try:
        tasks = [
            coordinator.submit(
                title="账号 A 任务",
                operation="browser.test",
                kind=TaskKind.JSHRSS_BROWSER,
                resource_key="account-a",
                resource_label="账号 A",
                runner=runner,
            ),
            coordinator.submit(
                title="账号 B 任务",
                operation="browser.test",
                kind=TaskKind.JSHRSS_BROWSER,
                resource_key="account-b",
                resource_label="账号 B",
                runner=runner,
            ),
        ]
        assert both_started.wait(1)
        assert peak == 2
        release.set()
        assert wait_until(
            lambda: all(
                coordinator.get(task.task_id).status is TaskStatus.SUCCEEDED
                for task in tasks
            )
        )
    finally:
        release.set()
        coordinator.close()


def test_api_queries_do_not_share_a_serial_resource_lock() -> None:
    coordinator = TaskCoordinator(max_workers=3)
    release = Event()
    both_started = Event()
    lock = Lock()
    started = 0

    def query(context):
        nonlocal started
        with lock:
            started += 1
            if started == 2:
                both_started.set()
        while not release.wait(0.01):
            context.raise_if_cancelled()

    try:
        coordinator.submit(
            title="查询一",
            operation="api.query",
            kind=TaskKind.API_QUERY,
            runner=query,
        )
        coordinator.submit(
            title="查询二",
            operation="api.query",
            kind=TaskKind.API_QUERY,
            runner=query,
        )
        assert both_started.wait(1)
    finally:
        release.set()
        coordinator.close()


def test_erp_writes_are_serialized_by_account_or_unit() -> None:
    coordinator = TaskCoordinator(max_workers=3)
    release = Event()
    first_started = Event()
    second_started = Event()

    def first(context):
        first_started.set()
        while not release.wait(0.01):
            context.raise_if_cancelled()

    def second(_context):
        second_started.set()

    try:
        coordinator.submit(
            title="ERP 写入一",
            operation="erp.write",
            kind=TaskKind.ERP_WRITE,
            resource_key="erp-account:unit-16",
            resource_label="第十六分公司",
            runner=first,
        )
        assert first_started.wait(1)
        queued = coordinator.submit(
            title="ERP 写入二",
            operation="erp.write",
            kind=TaskKind.ERP_WRITE,
            resource_key="erp-account:unit-16",
            resource_label="第十六分公司",
            runner=second,
        )
        snapshot = coordinator.get(queued.task_id)
        assert snapshot is not None
        assert snapshot.status is TaskStatus.QUEUED
        assert "普通查询不受影响" in snapshot.message
        assert not second_started.wait(0.1)
    finally:
        release.set()
        coordinator.close()


def test_queued_task_can_be_cancelled_without_running() -> None:
    coordinator = TaskCoordinator(max_workers=2)
    release = Event()
    first_started = Event()
    second_started = Event()

    def first(context):
        first_started.set()
        while not release.wait(0.01):
            context.raise_if_cancelled()

    try:
        coordinator.submit(
            title="当前任务",
            operation="browser.one",
            kind=TaskKind.JSHRSS_BROWSER,
            resource_key="same-account",
            resource_label="同一账号",
            runner=first,
        )
        assert first_started.wait(1)
        queued = coordinator.submit(
            title="等待任务",
            operation="browser.two",
            kind=TaskKind.JSHRSS_BROWSER,
            resource_key="same-account",
            resource_label="同一账号",
            runner=lambda _context: second_started.set(),
        )
        cancelled = coordinator.cancel(queued.task_id)
        assert cancelled is not None
        assert cancelled.status is TaskStatus.CANCELLED
        assert "不会执行任何业务操作" in cancelled.message
        release.set()
        assert not second_started.wait(0.2)
    finally:
        release.set()
        coordinator.close()
