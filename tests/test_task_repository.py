from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from ehrm.web.task_repository import TaskRepository
from ehrm.web.tasks import (
    TaskCoordinator,
    TaskKind,
    TaskOutcome,
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


def test_failed_business_outcome_keeps_results_and_error_after_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.sqlite3"
    result = {"succeeded": 0, "failed": 4, "artifacts": [{"name": "结果.xlsx", "url": "/api/v1/artifacts/test"}]}
    coordinator = TaskCoordinator(max_workers=1, store=TaskRepository(database))
    try:
        submitted = coordinator.submit(
            title="获取权益单", operation="rights_statement.acquire", kind=TaskKind.API_QUERY,
            runner=lambda _context: TaskOutcome(result, TaskStatus.FAILED, "权益单获取失败", "appCode=-1"),
        )
        assert wait_until(lambda: coordinator.get(submitted.task_id).status.terminal)
    finally:
        coordinator.close()
    restarted = TaskCoordinator(max_workers=1, store=TaskRepository(database))
    try:
        restored = restarted.get(submitted.task_id)
        assert restored.status is TaskStatus.FAILED
        assert restored.result == result
        assert restored.error == "appCode=-1"
        assert restored.message == "权益单获取失败"
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


def test_rights_usage_counts_acquisitions_once_and_groups_by_beijing_date(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    creations = [
        ("older", TaskStatus.SUCCEEDED, "2026-10-01T01:00:00+00:00"),
        ("before-midnight", TaskStatus.FAILED, "2026-10-12T15:59:59+00:00"),
        ("at-midnight", TaskStatus.SUCCEEDED, "2026-10-12T16:00:00+00:00"),
        ("queued", TaskStatus.QUEUED, "2026-10-13T00:00:00+00:00"),
        ("cancelled", TaskStatus.CANCELLED, "2026-10-13T10:00:00+08:00"),
        ("interrupted", TaskStatus.INTERRUPTED, "2026-10-13T03:00:00Z"),
    ]
    for task_id, status, created in creations:
        repository.save(replace(_snapshot(task_id, status), operation="rights_statement.acquire", created_at=created))
    for status in (TaskStatus.RUNNING, TaskStatus.SUCCEEDED):
        repository.save(replace(_snapshot("queued", status), operation="rights_statement.acquire"))
    repository.save(replace(_snapshot("erp-upload", TaskStatus.SUCCEEDED), operation="erp.rights.upload"))
    repository.save(replace(_snapshot("erp-extract", TaskStatus.SUCCEEDED), operation="erp.rights.extract"))

    stats = repository.rights_usage(days=3, now=datetime(2026, 10, 13, 6, tzinfo=UTC))
    assert stats["total_count"] == 6
    assert stats["today_count"] == 4
    assert stats["period_count"] == 5
    assert stats["first_used_date"] == "2026-10-01"
    assert stats["timezone"] == "Asia/Shanghai"
    assert stats["daily"] == [
        {"date": "2026-10-11", "count": 0},
        {"date": "2026-10-12", "count": 1},
        {"date": "2026-10-13", "count": 4},
    ]
    older_window = repository.rights_usage(start_date=date(2026, 10, 1), end_date=date(2026, 10, 2), now=datetime(2026, 10, 13, 6, tzinfo=UTC))
    assert older_window["total_count"] == 6
    assert older_window["today_count"] == 4
    assert older_window["period_count"] == 1
    assert older_window["daily"] == [{"date": "2026-10-01", "count": 1}, {"date": "2026-10-02", "count": 0}]


def test_rights_usage_reads_more_than_the_task_list_limit_and_survives_restart(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    repository = TaskRepository(database)
    snapshot = replace(_snapshot("seed", TaskStatus.FAILED), operation="rights_statement.acquire", created_at="2026-10-12T16:00:00+00:00")
    for index in range(505):
        repository.save(replace(snapshot, task_id=f"rights-{index}"))
    assert len(repository.list(limit=500)) == 500
    restored = TaskRepository(database).rights_usage(days=1, now=datetime(2026, 10, 13, 6, tzinfo=UTC))
    assert restored["total_count"] == 505
    assert restored["daily"] == [{"date": "2026-10-13", "count": 505}]


def test_empty_rights_usage_returns_a_complete_zero_filled_series(tmp_path: Path) -> None:
    stats = TaskRepository(tmp_path / "tasks.sqlite3").rights_usage(days=3, now=datetime(2026, 10, 13, 6, tzinfo=UTC))
    assert stats["total_count"] == stats["today_count"] == stats["period_count"] == 0
    assert stats["first_used_date"] is None
    assert stats["daily"] == [{"date": f"2026-10-{day}", "count": 0} for day in (11, 12, 13)]


def test_business_usage_separates_categories_without_double_counting(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    creations = [
        ("rights-old", "rights_statement.acquire", TaskStatus.SUCCEEDED, "2026-10-01T00:00:00Z"),
        ("rights-today", "rights_statement.acquire", TaskStatus.FAILED, "2026-10-12T16:00:00Z"),
        ("social-yesterday", "application.termination:run-1", TaskStatus.SUCCEEDED, "2026-10-12T15:59:59Z"),
        ("social-today", "application.termination:run-2", TaskStatus.QUEUED, "2026-10-13T00:00:00Z"),
        ("medical-old", "application.medical_enrollment:run-3", TaskStatus.SUCCEEDED, "2026-09-01T00:00:00Z"),
        ("medical-termination", "application.medical_termination:run-4", TaskStatus.CANCELLED, "2026-10-13T10:00:00+08:00"),
        ("medical-enrollment", "application.medical_enrollment:run-5", TaskStatus.INTERRUPTED, "2026-10-13T00:00:00Z"),
    ]
    for task_id, operation, status, created_at in creations:
        repository.save(replace(_snapshot(task_id, status), operation=operation, created_at=created_at))
    social = repository.get("social-today")
    repository.save(replace(social, status=TaskStatus.SUCCEEDED))
    for index, operation in enumerate(("erp.rights.upload", "erp.rights.extract", "scheduled:run-6", "application.medicalXtermination:run-7")):
        repository.save(replace(_snapshot(f"excluded-{index}", TaskStatus.SUCCEEDED), operation=operation))

    statistics = repository.business_usage(days=3, now=datetime(2026, 10, 13, 6, tzinfo=UTC))
    businesses = {item["key"]: item for item in statistics["businesses"]}
    assert [(item["key"], item["label"]) for item in statistics["businesses"]] == [("rights", "权益单"), ("social", "社保业务"), ("medical", "医保业务")]
    assert [(businesses[key]["total_count"], businesses[key]["today_count"], businesses[key]["period_count"]) for key in ("rights", "social", "medical")] == [(2, 1, 1), (2, 1, 2), (3, 2, 2)]
    assert businesses["social"]["daily"] == [{"date": "2026-10-11", "count": 0}, {"date": "2026-10-12", "count": 1}, {"date": "2026-10-13", "count": 1}]
    assert businesses["medical"]["first_used_date"] == "2026-09-01"
    assert businesses["medical"]["daily"][-1] == {"date": "2026-10-13", "count": 2}

    selected = repository.business_usage(start_date=date(2026, 9, 1), end_date=date(2026, 9, 1), now=datetime(2026, 10, 13, 6, tzinfo=UTC))
    assert [item["period_count"] for item in selected["businesses"]] == [0, 0, 1]
    assert [item["total_count"] for item in selected["businesses"]] == [2, 2, 3]
    assert [item["today_count"] for item in selected["businesses"]] == [1, 1, 2]


def test_empty_business_usage_keeps_all_categories_and_zero_fills_dates(tmp_path: Path) -> None:
    statistics = TaskRepository(tmp_path / "tasks.sqlite3").business_usage(days=3, now=datetime(2026, 10, 13, 6, tzinfo=UTC))
    assert len(statistics["businesses"]) == 3
    for business in statistics["businesses"]:
        assert business["total_count"] == business["today_count"] == business["period_count"] == 0
        assert business["first_used_date"] is None
        assert business["daily"] == [{"date": f"2026-10-{day}", "count": 0} for day in (11, 12, 13)]


@pytest.mark.parametrize("values", [
    {"days": 0}, {"days": 367}, {"start_date": date(2026, 10, 1)},
    {"start_date": date(2026, 10, 12), "end_date": date(2026, 10, 11)},
    {"start_date": date(2026, 10, 1), "end_date": date(2026, 10, 14)},
    {"start_date": date(2024, 1, 1), "end_date": date(2025, 1, 1)},
])
def test_rights_usage_rejects_invalid_windows(tmp_path: Path, values: dict) -> None:
    with pytest.raises(ValueError):
        TaskRepository(tmp_path / "tasks.sqlite3").rights_usage(**values, now=datetime(2026, 10, 13, 6, tzinfo=UTC))


def test_artifact_index_survives_repository_restart(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    artifact = tmp_path / "结果.zip"
    artifact.write_bytes(b"result")

    TaskRepository(database).save_artifact("stable-token", artifact)

    restored = TaskRepository(database).resolve_artifact("stable-token")
    assert restored == artifact.resolve()
