from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import Mock
import json

import pytest
from fastapi.testclient import TestClient

from ehrm.core.auth_repository import SystemType
from ehrm.core.settings import load_settings
from ehrm.modules.erp.models import ErpTaskRecord
from ehrm.modules.nocobase.erp_sync import ErpNocoBaseSync, SyncIdentityError, default_date_range, source_snapshot, source_changed
from ehrm.modules.nocobase.sync_client import NocoBaseSyncClient
from ehrm.modules.nocobase.exceptions import NocoBaseRequestError, NocoBaseApiKeyInvalidError
from ehrm.web.app import create_app
from ehrm.web.nocobase_sync import exclusive_file
from ehrm.web.tasks import TaskCoordinator, TaskKind


def record(**changes):
    return replace(ErpTaskRecord("erp-uuid", "RLSQ-test", "2026-09-29", "申请", "原文", "社保咨询",
                                 "50", "测试用户", "部门", {"RegHumId": "original-user"}), **changes)


class Target:
    def __init__(self, records=()):
        self.records = {item["key_value"]: item.copy() for item in records}
        self.writes = []
        self.users = []

    def find_application(self, key):
        return self.records.get(key)

    def find_user(self, name):
        self.users.append(name)
        return None, "未匹配用户"

    def create(self, values):
        saved = {"id": 123, "code": "NOCO-AUTO-123", "status": "NEW", **values}
        self.records[values["key_value"]] = saved
        self.writes.append(("create", values))
        return saved

    def update(self, record_id, values):
        saved = self.records[values["key_value"]]
        assert saved["id"] == record_id
        saved.update(values)
        self.writes.append(("update", values))
        return saved


def source(*records):
    erp = Mock()
    erp.query_tasks.side_effect = lambda kind, **kwargs: Mock(records=tuple(r for r in records if r.transaction_type == kind))
    return erp


def test_raw_sync_is_idempotent_and_no_ai_or_personnel():
    target = Target()
    service = ErpNocoBaseSync(source(record(), record(id="second", code="RLSQ-2", transaction_type="单位社保权益单")), target)
    first = service.run(start_date="2026-09-28", end_date="2026-09-29")
    second = service.run(start_date="2026-09-28", end_date="2026-09-29")
    assert first["summary"]["created"] == 2
    assert second["summary"]["unchanged"] == 2
    assert len(target.writes) == 2
    assert target.records["erp-uuid"]["prob_type"] == "social_security_consult"
    assert target.records["second"]["prob_type"] == "social_security_rights"
    assert target.records["erp-uuid"]["code"] == "NOCO-AUTO-123"
    assert target.records["erp-uuid"]["erp_code"] == "RLSQ-test"
    assert target.records["erp-uuid"]["initiator_id"] is None
    assert target.records["erp-uuid"]["erp_all_field_value"]["RegHumId"] == "original-user"
    assert all(not {"id", "code", "related_persons", "insurance_person", "termination_person", "attachments", "status", "handling_method"} & values.keys() for _, values in target.writes)
    assert len(target.users) == 1  # 同批次相同发起人只查询一次


@pytest.mark.parametrize("changes", [{"title": "新标题"}, {"description": "新描述"}, {"initiated_date": "2026-09-28"}])
def test_source_updates_preserve_manual_work(changes):
    original = record()
    saved = {"id": 321, "code": "NOCO-AUTO-321", "erp_code": original.code,
             "key_value": original.id, "erp_all_field_value": source_snapshot(original),
             "title": "人工标题", "status": "DONE", "handling_method": "已处理", "initiator_id": 9,
             "related_persons": [{"user_name": "人工人员"}], "prob_type": "social_security_enrollment"}
    target = Target([saved])
    same = ErpNocoBaseSync(source(original), target).run(start_date="2026-09-28", end_date="2026-09-29")
    assert same["summary"]["unchanged"] == 1
    changed = ErpNocoBaseSync(source(record(**changes)), target).run(start_date="2026-09-28", end_date="2026-09-29")
    assert changed["summary"]["updated"] == 1
    result = target.records[original.id]
    assert result["status"] == "DONE" and result["handling_method"] == "已处理"
    assert result["related_persons"] == saved["related_persons"] and result["initiator_id"] == 9
    assert result["code"] == "NOCO-AUTO-321"


def test_existing_legacy_record_backfills_erp_code_without_changing_nocobase_code():
    original = record()
    target = Target([{"id": 321, "code": "NOCO-AUTO-321", "key_value": original.id,
                      "erp_all_field_value": source_snapshot(original), "status": "DONE"}])
    service = ErpNocoBaseSync(source(original), target)
    preview = service.run(start_date="2026-09-29", end_date="2026-09-29", dry_run=True)
    assert preview["summary"]["would_update"] == 1
    assert not target.writes
    first = service.run(start_date="2026-09-29", end_date="2026-09-29")
    second = service.run(start_date="2026-09-29", end_date="2026-09-29")
    assert first["summary"]["updated"] == 1
    assert second["summary"]["unchanged"] == 1
    assert target.records[original.id]["erp_code"] == original.code
    assert target.records[original.id]["code"] == "NOCO-AUTO-321"
    assert target.records[original.id]["status"] == "DONE"
    assert len(target.writes) == 1
    assert "code" not in target.writes[0][1]


def test_dry_run_and_invalid_record_do_not_write():
    target = Target()
    result = ErpNocoBaseSync(source(record(), record(id="", code="invalid")), target).run(
        start_date="2026-09-28", end_date="2026-09-29", dry_run=True)
    assert result["summary"]["would_create"] == 1
    assert result["summary"]["failed"] == 1
    assert not target.writes


@pytest.mark.parametrize("missing_field", ["erp_code", "key_value"])
def test_missing_erp_identity_response_is_reported_not_silently_accepted(missing_field):
    target = Target()
    target.create = lambda values: {"id": 1, "code": "generated", **{
        key: value for key, value in values.items() if key != missing_field}}
    with pytest.raises(SyncIdentityError, match=missing_field):
        ErpNocoBaseSync(source(record()), target).run(start_date="2026-09-29", end_date="2026-09-29")


def test_lookup_result_with_wrong_key_value_stops_before_write():
    target = Target()
    target.find_application = lambda key: {"id": 321, "key_value": "another-erp-id"}
    with pytest.raises(SyncIdentityError, match="key_value"):
        ErpNocoBaseSync(source(record()), target).run(start_date="2026-09-29", end_date="2026-09-29")
    assert not target.writes


class Response:
    def __init__(self, data, status=200):
        self.data, self.status, self.disposed = data, status, False
    def json(self):
        return self.data
    def dispose(self):
        self.disposed = True


def client(tmp_path, payload, status=200):
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    response = Response(payload, status)
    request = Mock()
    request.fetch.return_value = response
    return NocoBaseSyncClient(settings.nocobase, request, "secret-test-key"), request, response


def test_lookup_uses_erp_key_not_type_or_date(tmp_path):
    api, request, response = client(tmp_path, {"data": [], "meta": {"count": 0}})
    assert api.find_application("erp-id") is None
    values = request.fetch.call_args.kwargs
    assert json.loads(values["params"]["filter"]) == {"key_value": {"$eq": "erp-id"}}
    assert "prob_type" not in values["params"]["filter"] and response.disposed


def test_duplicate_and_ambiguous_users_are_not_arbitrarily_selected(tmp_path):
    api, request, _ = client(tmp_path, {"data": [{"id": 1}, {"id": 2}], "meta": {"count": 2}})
    with pytest.raises(NocoBaseRequestError, match="多条申请"):
        api.find_application("erp-id")
    assert api.find_user("姓名")[0] is None
    request.fetch.return_value = Response({"data": [{"id": 3}], "meta": {"count": 1}})
    assert api.find_user("姓名") == (3, "")


def test_post_is_minimal_and_uses_filter_by_tk(tmp_path):
    api, request, response = client(tmp_path, {"data": [{"id": 123, "code": "ERP"}]})
    assert api.update(123, {"title": "changed"})["id"] == 123
    values = request.fetch.call_args.kwargs
    assert values["params"] == {"filterByTk": "123"}
    assert values["data"] == {"title": "changed"} and values["method"] == "POST"
    assert "updateAssociationValues" not in str(request.fetch.call_args)
    assert response.disposed


def test_key_is_not_echoed_on_upstream_error(tmp_path):
    api, _, response = client(tmp_path, {"errors": [{"message": "secret-test-key"}]})
    with pytest.raises(NocoBaseRequestError) as error:
        api.find_application("erp-id")
    assert "secret-test-key" not in str(error.value) and response.disposed
    api, _, response = client(tmp_path, {}, 401)
    with pytest.raises(NocoBaseApiKeyInvalidError):
        api.find_application("erp-id")
    assert response.disposed


def test_os_lock_and_default_window(tmp_path):
    with exclusive_file(tmp_path / "run.lock") as first:
        with exclusive_file(tmp_path / "run.lock") as second:
            assert first and not second
    with exclusive_file(tmp_path / "run.lock") as third:
        assert third
    assert default_date_range(2, today=date(2026, 1, 1)) == ("2025-12-31", "2026-01-01")


def test_legacy_date_is_compared_in_shanghai_timezone():
    assert not source_changed(record(), {"title": "申请", "problem_desc": "原文",
                                         "initiation_date": "2026-09-28T16:00:00.000Z"})


def test_remote_identity_failure_disposes_request(tmp_path, monkeypatch):
    from ehrm.web import nocobase_sync as module
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=1)
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    controller = app.state.nocobase_sync
    monkeypatch.setattr(module, "ErpTaskQueryService", lambda *args: source(record()))
    target = Target()
    target.create = lambda values: {"id": 88, "code": "generated", "key_value": values["key_value"]}
    monkeypatch.setattr(module, "NocoBaseSyncClient", lambda *args: target)
    request = Mock()
    playwright = MagicMock()
    playwright.__enter__.return_value.request.new_context.return_value = request
    monkeypatch.setattr(module, "sync_playwright", lambda: playwright)
    try:
        with pytest.raises(SyncIdentityError, match="88"):
            controller._run(Mock(), settings, "test-key", SimpleNamespace(account="user", password="pass"),
                            "2026-09-28", "2026-09-29", False)
        request.dispose.assert_called_once()
    finally:
        coordinator.close()


def test_script_preview_waits_without_starting_service(monkeypatch, capsys):
    from scripts import run_erp_nocobase_sync as script
    from io import StringIO
    requests = []
    responses = [
        {"task_id": "abc", "title": "预览 ERP 同步计划"},
        {"task_id": "abc", "message": "预览结束", "status": "succeeded",
         "result": {"dry_run": True, "summary": {"failed": 0, "would_create": 1}}},
    ]
    def open_response(request, **kwargs):
        requests.append(request)
        return StringIO(json.dumps(responses.pop(0)))
    monkeypatch.setattr(script, "urlopen", open_response)
    assert script.main(["--dry-run", "--start-date", "2026-09-28", "--end-date", "2026-09-29"]) == 0
    assert json.loads(requests[0].data)["dry_run"] is True
    assert requests[1].full_url.endswith("/api/v1/tasks/abc")
    assert "would_create" in capsys.readouterr().out
