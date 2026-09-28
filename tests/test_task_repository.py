from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ehrm.web.task_repository import TaskRepository
from ehrm.web.tasks import (
    TaskCoordinator,
    TaskKind,
    TaskSnapshot,
    TaskStatus,
    wait_until,
)


def _snapshot(
    task_id: str,
    status: TaskStatus,
    *,
    result: object | None = None,
) -> TaskSnapshot:
    now = datetime.now(UTC).isoformat()
    return TaskSnapshot(
        task_id=task_id,
        title=f"任务 {task_id}",
        operation="test.operation",
        kind=TaskKind.API_QUERY,
        status=status,
        resource_label="测试资源",
        queue_position=0,
        message="测试说明",
        progress_current=1 if status.terminal else 0,
        progress_total=1,
        created_at=now,
        started_at=now if status is not TaskStatus.QUEUED else None,
        finished_at=now if status.terminal else None,
        result=result,
        error="",
    )


def test_task_record_survives_repository_and_coordinator_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.sqlite3"
    repository = TaskRepository(database)
    coordinator = TaskCoordinator(max_workers=1, store=repository)
    try:
        submitted = coordinator.submit(
            title="持久化任务",
            operation="test.persist",
            kind=TaskKind.API_QUERY,
            runner=lambda _context: {"count": 3},
        )
        assert wait_until(
            lambda: coordinator.get(submitted.task_id).status
            is TaskStatus.SUCCEEDED
        )
    finally:
        coordinator.close()

    restarted = TaskCoordinator(max_workers=1, store=TaskRepository(database))
    try:
        restored = restarted.get(submitted.task_id)
        assert restored is not None
        assert restored.status is TaskStatus.SUCCEEDED
        assert restored.result == {"count": 3}
        assert restarted.list(limit=10)[0].task_id == submitted.task_id
    finally:
        restarted.close()


def test_restart_marks_unfinished_tasks_interrupted_without_rerunning(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.sqlite3"
    repository = TaskRepository(database)
    repository.save(_snapshot("queued", TaskStatus.QUEUED))
    repository.save(_snapshot("running", TaskStatus.RUNNING))
    repository.save(_snapshot("cancelling", TaskStatus.CANCELLING))
    repository.save(_snapshot("completed", TaskStatus.SUCCEEDED))

    coordinator = TaskCoordinator(max_workers=1, store=TaskRepository(database))
    try:
        for task_id in ("queued", "running", "cancelling"):
            restored = coordinator.get(task_id)
            assert restored is not None
            assert restored.status is TaskStatus.INTERRUPTED
            assert "重新发起" in restored.message
        assert coordinator.get("completed").status is TaskStatus.SUCCEEDED
    finally:
        coordinator.close()


def test_task_records_are_not_automatically_deleted(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    repository = TaskRepository(database)
    repository.save(_snapshot("first", TaskStatus.SUCCEEDED))

    for _ in range(3):
        repository = TaskRepository(database)

    assert repository.get("first") is not None


def test_artifact_index_survives_repository_restart(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    artifact = tmp_path / "结果.zip"
    artifact.write_bytes(b"result")

    TaskRepository(database).save_artifact("stable-token", artifact)

    restored = TaskRepository(database).resolve_artifact("stable-token")
    assert restored == artifact.resolve()
