from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import threading
import time
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from ehrm.core.settings import load_settings
from ehrm.modules.nocobase.erp_sync import SyncIdentityError
from ehrm.web.app import create_app
from ehrm.core.cron_schedule import TIMEZONE, upcoming
from ehrm.web.nocobase_sync import read_legacy_schedule
from ehrm.web.schedule_repository import ScheduleRepository
from ehrm.web.scheduled_tasks import DEFAULT_JOB
from ehrm.web.task_repository import TaskRepository
from ehrm.web.tasks import TaskCoordinator, TaskKind


VALUES = dict(name="ERP 同步", task_type="erp_nocobase_sync", cron="0 8 * * *", enabled=False, lookback_days=2)


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=2, store=TaskRepository(tmp_path / "tasks.sqlite3"))
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    controller = app.state.nocobase_sync
    monkeypatch.setattr(controller, "prepare", lambda: (settings, "secret-test-key", SimpleNamespace(id=7, display_name="ERP", account="user", password="pass")))
    monkeypatch.setattr(controller, "_run", lambda context, *args: {"summary": {"created": 1, "failed": 0}})
    yield app, app.state.scheduled_tasks, coordinator, controller
    app.state.scheduled_tasks.close()
    coordinator.close()


def finished(workbench, run_id):
    limit = time.monotonic() + 3
    while time.monotonic() < limit:
        run = workbench.repository.run(run_id)
        if run["status"] not in ("queued", "running", "cancelling"):
            return run
        time.sleep(.01)
    raise AssertionError("task did not finish")


def test_cron_unix_weekday_or_semantics_and_impossible_date():
    start = datetime(2026, 9, 29, 12, tzinfo=TIMEZONE)  # Tuesday
    assert upcoming("0 8 * * 0", count=1, now=start) == ["2026-10-04T08:00:00+08:00"]
    assert upcoming("0 8 * * 7", count=1, now=start) == upcoming("0 8 * * sun", count=1, now=start)
    assert upcoming("0 8 * * 1-5", count=1, now=start)[0].startswith("2026-09-30")
    assert upcoming("0 8 1 * mon", count=2, now=start) == ["2026-10-01T08:00:00+08:00", "2026-10-05T08:00:00+08:00"]
    assert upcoming("0 8 */1 * mon", count=1, now=start) == ["2026-10-05T08:00:00+08:00"]
    for expression in ("* * * * * *", "0 25 * * *", "0 8 * * 8", "0 8 31 2 *", "@daily"):
        with pytest.raises(ValueError):
            upcoming(expression)


def test_job_api_preview_validation_and_persistence(workbench):
    app, bench, _, _ = workbench
    with TestClient(app) as web:
        assert web.get("/api/v1/scheduled-tasks").json()["jobs"][0]["enabled"] is False
        assert web.get("/api/v1/scheduled-tasks/cron-preview", params={"cron": "0 8 * * mon"}).json()["times"]
        assert web.put(f"/api/v1/scheduled-tasks/{DEFAULT_JOB}", json={**VALUES, "cron": "bad"}).status_code == 400
        assert web.put(f"/api/v1/scheduled-tasks/{DEFAULT_JOB}", json={**VALUES, "lookback_days": 0}).status_code == 422
        assert web.post("/api/v1/scheduled-tasks", json={**VALUES, "task_type": "shell"}).status_code == 400
        assert web.post("/api/v1/scheduled-tasks", json={**VALUES, "command": "arbitrary"}).status_code == 422
        created = web.post("/api/v1/scheduled-tasks", json=VALUES).json()
        assert created["id"] != DEFAULT_JOB
        saved = web.put(f"/api/v1/scheduled-tasks/{DEFAULT_JOB}", json={**VALUES, "enabled": True}).json()
        assert saved["enabled"] and saved["next_run"]
        assert bench.scheduler.get_job(DEFAULT_JOB)
    assert not bench.scheduler.running
    restored = ScheduleRepository(bench.repository.path).job(DEFAULT_JOB)
    assert restored["enabled"] and restored["cron"] == VALUES["cron"]


def test_manual_and_automatic_overlap_are_logged_without_moving_plan(workbench, monkeypatch):
    app, bench, coordinator, controller = workbench
    release = threading.Event()
    entered = threading.Event()
    def execute(context, *args):
        entered.set()
        context.report("步骤一：获取 ERP 申请")
        release.wait(3)
        context.report("步骤二：同步完成")
        return {"summary": {"created": 1, "failed": 0}}
    monkeypatch.setattr(controller, "_run", execute)
    try:
        with TestClient(app) as web:
            saved = bench.save(DEFAULT_JOB, {**VALUES, "enabled": True})
            assert web.post("/api/v1/nocobase/sync", json={"start_date": "2026-09-28"}).status_code == 400
            first = web.post(f"/api/v1/scheduled-tasks/{DEFAULT_JOB}/run", json={"dry_run": True}).json()
            assert entered.wait(1)
            assert bench.repository.job(DEFAULT_JOB)["next_run"] == saved["next_run"]
            second = web.post(f"/api/v1/scheduled-tasks/{DEFAULT_JOB}/run", json={}).json()
            assert second["status"] == "skipped" and second["task_id"] == first["task_id"]
            bench._fire(DEFAULT_JOB)
            legacy_cli = web.post("/api/v1/nocobase/sync", json={}).json()
            assert legacy_cli["task_id"] == first["task_id"]
            assert coordinator.get(first["task_id"]).kind == TaskKind.ERP_BROWSER
            release.set()
            done = finished(bench, first["id"])
            assert done["status"] == "succeeded"
            history = web.get("/api/v1/scheduled-runs", params={"page_size": 2}).json()
            assert history["total"] == 4 and len(history["items"]) == 2
            logs = web.get(f"/api/v1/scheduled-runs/{first['id']}/logs").json()
            assert any("步骤一" in log["message"] for log in logs["items"])
            assert any("步骤二" in log["message"] for log in logs["items"])
            assert "secret-test-key" not in str(history) + str(logs)
    finally:
        release.set()


def test_existing_erp_queue_and_cancel_before_start(workbench):
    _, bench, coordinator, _ = workbench
    release = threading.Event()
    entered = threading.Event()
    def runner(context):
        entered.set()
        release.wait(3)
    try:
        coordinator.submit(title="其他 ERP 操作", operation="erp.other", kind=TaskKind.ERP_BROWSER,
                           resource_key="7", runner=runner)
        assert entered.wait(1)
        run = bench.trigger(DEFAULT_JOB)
        assert run["status"] == "queued"
        coordinator.cancel(run["task_id"])
        assert bench.repository.run(run["id"])["status"] == "cancelled"
        assert bench.repository.active("erp_nocobase_sync") is None
    finally:
        release.set()


def test_partial_failure_and_identity_error_pause(workbench, monkeypatch):
    _, bench, _, controller = workbench
    monkeypatch.setattr(controller, "_run", lambda *args: {"summary": {"failed": 1}})
    run = bench.trigger(DEFAULT_JOB)
    assert finished(bench, run["id"])["status"] == "partial_failed"
    bench.save(DEFAULT_JOB, {**VALUES, "enabled": True})
    other = bench.save(None, {**VALUES, "name": "其他同类计划", "enabled": True})
    def fail(*args):
        raise SyncIdentityError("远端编号被修改", details="远端记录 ID=123")
    monkeypatch.setattr(controller, "_run", fail)
    run = bench.trigger(DEFAULT_JOB)
    assert finished(bench, run["id"])["status"] == "failed"
    job = bench.repository.job(DEFAULT_JOB)
    assert not job["enabled"] and job["next_run"] is None and "自动执行已暂停" in job["notice"]
    assert "123" in bench.repository.run(run["id"])["error"]
    assert not bench.repository.job(other["id"])["enabled"]


def test_missing_credentials_records_failed_attempt(workbench, monkeypatch):
    _, bench, _, controller = workbench
    def missing():
        raise ValueError("请先配置 ERP 账号和密码")
    monkeypatch.setattr(controller, "prepare", missing)
    with pytest.raises(ValueError):
        bench.save(DEFAULT_JOB, {**VALUES, "enabled": True})
    assert not bench.repository.job(DEFAULT_JOB)["enabled"]
    with pytest.raises(ValueError):
        bench.trigger(DEFAULT_JOB)
    record = bench.repository.runs()["items"][0]
    assert record["status"] == "failed" and record["task_id"] is None
    assert bench.repository.logs(record["id"])["items"][-1]["level"] == "error"


def test_engine_skips_are_durable_and_not_active(workbench):
    from apscheduler.events import EVENT_JOB_MAX_INSTANCES
    _, bench, _, _ = workbench
    bench._engine_skip(SimpleNamespace(job_id=DEFAULT_JOB, code=EVENT_JOB_MAX_INSTANCES))
    run = bench.repository.runs()["items"][0]
    assert run["status"] == "skipped" and run["trigger_kind"] == "automatic"
    assert bench.repository.active("erp_nocobase_sync") is None
    assert finished(bench, bench.trigger(DEFAULT_JOB)["id"])["status"] == "succeeded"


def test_late_callback_does_not_overwrite_disabled_or_edited_plan(workbench):
    _, bench, _, _ = workbench
    bench.save(DEFAULT_JOB, VALUES)
    bench.repository.next_run(DEFAULT_JOB, "2099-01-01T00:00:00+08:00", VALUES["cron"])
    assert bench.repository.job(DEFAULT_JOB)["next_run"] is None
    saved = bench.save(DEFAULT_JOB, {**VALUES, "cron": "0 9 * * *", "enabled": True})
    bench.repository.next_run(DEFAULT_JOB, "2099-01-01T00:00:00+08:00", VALUES["cron"])
    assert bench.repository.job(DEFAULT_JOB)["next_run"] == saved["next_run"]


def test_restart_preserves_history_and_recovers_unfinished_without_replay(workbench):
    _, bench, _, _ = workbench
    orphan = bench.repository.new_run(DEFAULT_JOB, "manual", {})
    bench.start()
    assert bench.repository.run(orphan)["status"] == "interrupted"
    assert bench.repository.runs()["total"] == 1
    assert bench.repository.job(DEFAULT_JOB)["enabled"] is False


def test_persisted_overdue_cron_coalesces_to_one_execution(workbench, monkeypatch):
    _, bench, _, controller = workbench
    calls = []
    ran = threading.Event()
    def execute(*args):
        calls.append(True)
        ran.set()
        return {"summary": {"failed": 0}}
    monkeypatch.setattr(controller, "_run", execute)
    job = bench.repository.job(DEFAULT_JOB)
    job.update(enabled=True, cron="*/5 * * * *", next_run=(datetime.now(TIMEZONE) - timedelta(hours=2)).isoformat())
    bench.repository.save(job)
    bench.start()
    assert ran.wait(2)
    time.sleep(.05)
    assert len(calls) == 1 and bench.repository.runs()["total"] == 1
    assert datetime.fromisoformat(bench.repository.job(DEFAULT_JOB)["next_run"]) > datetime.now(TIMEZONE)


def test_legacy_plan_migration_keeps_days_but_requires_confirmation(tmp_path):
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    first = create_app(settings=settings, logger=Mock())
    first.state.task_coordinator.close()
    # Separate installation directory containing just the legacy database.
    from ehrm.web.scheduled_tasks import ScheduledTaskWorkbench
    from ehrm.web.nocobase_sync import NocoBaseSyncController
    coordinator = TaskCoordinator(max_workers=1)
    service = first.state.web_settings_service
    migration_root = tmp_path / "legacy-only"
    controller = NocoBaseSyncController(service, coordinator, Mock())
    controller.root = migration_root
    import sqlite3
    migration_root.mkdir()
    legacy = migration_root / "nocobase_sync.sqlite3"
    with sqlite3.connect(legacy) as db:
        db.execute("CREATE TABLE sync_schedule(id INTEGER PRIMARY KEY, interval_minutes INTEGER, lookback_days INTEGER)")
        db.execute("INSERT INTO sync_schedule VALUES(1,45,7)")
    bench = ScheduledTaskWorkbench(controller)
    try:
        job = bench.repository.job(DEFAULT_JOB)
        assert not job["enabled"] and job["lookback_days"] == 7 and "45" in job["notice"]
        assert read_legacy_schedule(legacy) == {"interval_minutes": 45, "lookback_days": 7}
    finally:
        bench.close()
        coordinator.close()
