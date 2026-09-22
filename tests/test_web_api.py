from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
from datetime import datetime

from fastapi.testclient import TestClient

from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.settings import load_settings
from ehrm.gui.template_service import RightsStatementTemplateService
from ehrm.modules.rights_statement.excel_models import EmployeeRecord
from ehrm.modules.nocobase.models import (
    NocoBaseRelatedPerson,
    NocoBaseRightsApplicationDetail,
)
from ehrm.web.app import create_app
from ehrm.web.tasks import TaskCoordinator, TaskKind, TaskStatus, wait_until
from ehrm.modules.erp.extraction_service import ErpTaskExtractionService


def _client(tmp_path: Path) -> tuple[TestClient, TaskCoordinator]:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=2)
    app = create_app(
        settings=settings,
        logger=Mock(),
        coordinator=coordinator,
    )
    return TestClient(app), coordinator


def test_web_health_and_concurrency_policy_are_explicit(tmp_path: Path) -> None:
    client, coordinator = _client(tmp_path)
    try:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["deployment"] == "single-server"

        response = client.get("/api/v1/concurrency-policy")
        assert response.status_code == 200
        items = response.json()["items"]
        assert items[0]["situation"] == "同一智慧人社账号"
        assert items[0]["behavior"] == "串行排队"
        assert items[1]["behavior"] == "独立浏览器并行"
        assert items[2]["behavior"] == "直接并行"
    finally:
        coordinator.close()


def test_built_web_client_is_served_for_root_and_client_routes(
    tmp_path: Path,
) -> None:
    client, coordinator = _client(tmp_path)
    try:
        root = client.get("/")
        assert root.status_code == 200
        assert "text/html" in root.headers["content-type"]
        assert '<div id="root"></div>' in root.text

        client_route = client.get("/tasks")
        assert client_route.status_code == 200
        assert '<div id="root"></div>' in client_route.text
    finally:
        coordinator.close()


def test_pdf_artifact_supports_inline_preview_and_download(tmp_path: Path) -> None:
    client, coordinator = _client(tmp_path)
    pdf = tmp_path / "权益单.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    artifact = client.app.state.rights_service.artifacts.register(pdf)
    try:
        preview = client.get(f"{artifact['url']}?preview=true")
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "application/pdf"
        assert preview.headers["content-disposition"].startswith("inline")

        download = client.get(artifact["url"])
        assert download.status_code == 200
        assert download.headers["content-disposition"].startswith("attachment")
    finally:
        coordinator.close()


def test_accounts_endpoint_never_exposes_password_or_full_account(
    tmp_path: Path,
) -> None:
    client, coordinator = _client(tmp_path)
    settings = client.app.state.settings
    AuthenticationRepository(settings.auth_database_path).save_account(
        SystemType.JSHRSS,
        "91320000134757308F",
        "secret-password",
        secondary_account="13800138000",
        display_name="南京测试单位",
    )
    try:
        response = client.get("/api/v1/accounts")
        assert response.status_code == 200
        payload = response.json()
        assert payload[0]["display_name"] == "南京测试单位"
        assert payload[0]["ready"] is True
        serialized = response.text
        assert "secret-password" not in serialized
        assert "91320000134757308F" not in serialized
        assert "91" in payload[0]["masked_account"]
        assert payload[0]["masked_account"].endswith("8F")
    finally:
        coordinator.close()


def test_task_api_and_websocket_return_friendly_task_state(tmp_path: Path) -> None:
    client, coordinator = _client(tmp_path)
    release = __import__("threading").Event()

    def runner(context):
        context.report("正在核对人员信息", current=1, total=3)
        while not release.wait(0.01):
            context.raise_if_cancelled()

    task = coordinator.submit(
        title="人员参保登记",
        operation="enrollment.prepare",
        kind=TaskKind.JSHRSS_BROWSER,
        resource_key="account-1",
        resource_label="南京测试单位",
        runner=runner,
    )
    try:
        response = client.get("/api/v1/tasks")
        assert response.status_code == 200
        assert response.json()["tasks"][0]["task_id"] == task.task_id

        with client.websocket_connect("/api/v1/tasks/ws") as websocket:
            payload = websocket.receive_json()
            assert payload["tasks"][0]["title"] == "人员参保登记"
            assert payload["tasks"][0]["message"]

        cancelled = client.post(f"/api/v1/tasks/{task.task_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] in {"cancelling", "cancelled"}
    finally:
        release.set()
        coordinator.close()


def test_web_settings_can_update_preferences_and_preserve_saved_password(
    tmp_path: Path,
) -> None:
    client, coordinator = _client(tmp_path)
    repository = AuthenticationRepository(client.app.state.settings.auth_database_path)
    account = repository.save_account(
        SystemType.JSHRSS,
        "unit-account",
        "saved-password",
        secondary_account="mobile-id",
        display_name="原名称",
    )
    try:
        edit_detail = client.get(
            f"/api/v1/settings/accounts/JSHRSS?account_id={account.id}"
        )
        assert edit_detail.status_code == 200
        assert edit_detail.json() == {
            "id": account.id,
            "system_type": "JSHRSS",
            "display_name": "原名称",
            "account": "unit-account",
            "secondary_account": "mobile-id",
            "password_mask": "******",
            "password_saved": True,
        }
        assert "saved-password" not in edit_detail.text

        preferences = client.get("/api/v1/settings")
        assert preferences.status_code == 200
        payload = preferences.json()
        payload.update(
            {
                "output_path": str(tmp_path / "downloads"),
                "export_mode": "batch",
                "batch_size": 30,
                "execution_speed": "stable",
            }
        )
        for key in (
            "ai_model_options",
            "active_ai_model",
            "active_reasoning_mode",
        ):
            payload.pop(key)
        saved = client.put("/api/v1/settings/preferences", json=payload)
        assert saved.status_code == 200
        assert saved.json()["preferences"]["batch_size"] == 30

        account_response = client.put(
            "/api/v1/settings/accounts/JSHRSS",
            json={
                "account_id": account.id,
                "account": "",
                "secondary_account": "",
                "password": "",
                "display_name": "Web 修改后名称",
            },
        )
        assert account_response.status_code == 200
        reloaded = repository.get_default_account(SystemType.JSHRSS)
        assert reloaded is not None
        assert reloaded.account == "unit-account"
        assert reloaded.password == "saved-password"
        assert reloaded.display_name == "Web 修改后名称"
    finally:
        coordinator.close()


def test_rights_excel_import_can_start_account_scoped_task(tmp_path: Path) -> None:
    client, coordinator = _client(tmp_path)
    repository = AuthenticationRepository(client.app.state.settings.auth_database_path)
    account = repository.save_account(
        SystemType.JSHRSS,
        "unit-account",
        "saved-password",
        secondary_account="mobile-id",
        display_name="南京测试单位",
    )
    source = RightsStatementTemplateService().write_records(
        tmp_path / "rights.xlsx",
        [
            EmployeeRecord(
                row_number=2,
                unit="南京南化建设有限公司",
                department="第十六分公司",
                name="张三",
                identity_number="320101199001011234",
                insurance_type="养老",
                start_month="2026-01",
                end_month="2026-06",
                task_number="RLSQ-TEST-001",
            )
        ],
        include_print_groups=False,
    )
    client.app.state.rights_service._run = lambda context, selected, request: {
        "account_id": selected.id,
        "groups": len(request.groups),
        "upload_to_erp": request.upload_to_erp,
    }
    try:
        imported = client.post(
            "/api/v1/rights/import",
            files={
                "file": (
                    source.name,
                    source.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert imported.status_code == 200
        preview = imported.json()
        assert preview["record_count"] == 1
        assert "199001" not in preview["records"][0]["identity_number"]

        started = client.post(
            "/api/v1/rights/tasks",
            json={
                "import_id": preview["import_id"],
                "account_id": account.id,
                "export_mode": "individual",
                "batch_size": 50,
                "upload_to_erp": True,
            },
        )
        assert started.status_code == 200
        task_id = started.json()["task_id"]
        assert wait_until(
            lambda: coordinator.get(task_id).status is TaskStatus.SUCCEEDED
        )
        assert coordinator.get(task_id).result == {
            "account_id": account.id,
            "groups": 1,
            "upload_to_erp": True,
        }

        template = client.get("/api/v1/rights/template")
        assert template.status_code == 200
        assert template.content.startswith(b"PK")
    finally:
        coordinator.close()


def test_erp_application_extraction_returns_rights_preview_on_same_page(
    tmp_path: Path,
) -> None:
    client, coordinator = _client(tmp_path)
    repository = AuthenticationRepository(client.app.state.settings.auth_database_path)
    account = repository.save_account(
        SystemType.ERP,
        "erp-user",
        "erp-password",
        display_name="ERP 测试账号",
    )
    extraction_result = {
        "query": {"transaction_type": "项目社保申请挂靠", "selected_count": 1},
        "model": {"name": "qwen-test", "reasoning_mode": "off"},
        "summary": {
            "tasks_total": 1,
            "tasks_succeeded": 1,
            "tasks_failed": 0,
            "people_extracted": 1,
        },
        "tasks": [
            {
                "sequence": 1,
                "task_number": "RLSQ-ERP-001",
                "title": "权益单申请",
                "description": "张三申请养老权益单",
                "status_label": "35（生效）",
                "originator": "测试人",
                "department": "人力资源部",
                "parse_status": {"code": "SUCCESS", "message": "成功"},
            }
        ],
        "rights_statement_requests": [
            {
                "task_number": "RLSQ-ERP-001",
                "group_id": "RLSQ-ERP-001-G01",
                "group_sequence": 1,
                "group_people_count": 2,
                "name": "张三",
                "social_security_number": "320101199001011234",
                "insurance_type": "养老",
                "start_month": "2026-01",
                "end_month": "2026-06",
                "resolved_print_mode": "combined",
                "review_reasons": [],
                "warnings": [],
                "identity_match": {
                    "code": "SUCCESS",
                    "company": "南京南化建设有限公司",
                    "department": "第十六分公司",
                },
            },
            {
                "task_number": "RLSQ-ERP-001",
                "group_id": "RLSQ-ERP-001-G01",
                "group_sequence": 1,
                "group_people_count": 2,
                "name": "李四",
                "social_security_number": "320101199002021235",
                "insurance_type": "养老",
                "start_month": "2026-01",
                "end_month": "2026-06",
                "resolved_print_mode": "combined",
                "review_reasons": [],
                "warnings": [],
                "identity_match": {
                    "code": "SUCCESS",
                    "company": "南京南化建设有限公司",
                    "department": "第十六分公司",
                },
            },
            {
                "task_number": "RLSQ-ERP-001",
                "group_id": "RLSQ-ERP-001-G02",
                "group_sequence": 2,
                "group_people_count": 1,
                "name": "张三",
                "social_security_number": "320101199001011234",
                "insurance_type": "养老",
                "start_month": "2026-07",
                "end_month": "2026-08",
                "resolved_print_mode": "individual",
                "review_reasons": [],
                "warnings": [],
                "identity_match": {
                    "code": "SUCCESS",
                    "company": "南京南化建设有限公司",
                    "department": "第十六分公司",
                },
            },
        ],
    }
    try:
        with patch.object(
            ErpTaskExtractionService,
            "run",
            return_value=extraction_result,
        ):
            started = client.post(
                "/api/v1/rights/erp-extraction",
                json={
                    "account_id": account.id,
                    "transaction_type": "项目社保申请挂靠",
                    "statuses": [35],
                    "application_code": "",
                    "start_date": "",
                    "end_date": "",
                    "page_size": 50,
                    "reasoning_mode": "off",
                },
            )
            assert started.status_code == 200
            assert started.json()["kind"] == "erp_browser"
            task_id = started.json()["task_id"]
            assert wait_until(
                lambda: coordinator.get(task_id).status is TaskStatus.SUCCEEDED
            )

        detail = client.get(f"/api/v1/tasks/{task_id}")
        assert detail.status_code == 200
        preview = detail.json()["result"]["preview"]
        assert preview["source"] == "erp"
        assert preview["record_count"] == 3
        assert preview["unique_person_count"] == 2
        assert preview["group_count"] == 2
        assert preview["executable"] is True
        assert preview["records"][0]["name"] == "张三"
        assert "199001" not in preview["records"][0]["identity_number"]
        assert [group["people_count"] for group in preview["print_groups"]] == [2, 1]
        assert [person["name"] for person in preview["print_groups"][1]["people"]] == ["张三"]
        assert preview["applications"][0]["description"] == "张三申请养老权益单"
    finally:
        coordinator.close()


def test_erp_application_extraction_reports_empty_query_as_failure(
    tmp_path: Path,
) -> None:
    client, coordinator = _client(tmp_path)
    repository = AuthenticationRepository(client.app.state.settings.auth_database_path)
    account = repository.save_account(
        SystemType.ERP,
        "erp-user",
        "erp-password",
        display_name="ERP 测试账号",
    )
    extraction_result = {
        "query": {
            "transaction_type": "项目社保申请挂靠",
            "application_code": "RLSQ20260919-0001",
            "status_labels": [],
            "selected_count": 0,
        },
        "summary": {"tasks_total": 0, "people_extracted": 0},
        "tasks": [],
        "rights_statement_requests": [],
    }
    try:
        with patch.object(
            ErpTaskExtractionService,
            "run",
            return_value=extraction_result,
        ):
            started = client.post(
                "/api/v1/rights/erp-extraction",
                json={
                    "account_id": account.id,
                    "transaction_type": "项目社保申请挂靠",
                    "statuses": [],
                    "application_code": "RLSQ20260919-0001",
                    "start_date": "",
                    "end_date": "",
                    "page_size": 50,
                    "reasoning_mode": "",
                },
            )
            task_id = started.json()["task_id"]
            assert wait_until(
                lambda: coordinator.get(task_id).status is TaskStatus.FAILED
            )

        task = client.get(f"/api/v1/tasks/{task_id}").json()
        assert "未查询到符合条件的 ERP 申请" in task["error"]
        assert "申请状态：全部状态" in task["error"]
        assert task["result"] is None
    finally:
        coordinator.close()


def test_nocobase_detail_can_start_rights_print_task(tmp_path: Path) -> None:
    client, coordinator = _client(tmp_path)
    repository = AuthenticationRepository(client.app.state.settings.auth_database_path)
    account = repository.save_account(
        SystemType.JSHRSS,
        "unit-account",
        "saved-password",
        secondary_account="mobile-id",
    )
    detail = NocoBaseRightsApplicationDetail(
        application_id=1001,
        code="RLSQ20260921-0001",
        status="NEW",
        title="权益单申请",
        problem_type="social_security_rights",
        created_at=None,
        initiation_date=None,
        estimate_time=0,
        actual_time=0,
        estimate_date=None,
        actual_date=None,
        created_by_name="测试人",
        initiator_name="测试人",
        problem_description="",
        handling_method="",
        related_persons=(
            NocoBaseRelatedPerson(
                person_id=2001,
                status="NEW",
                insurance_type="elderly_care",
                start_month=datetime(2026, 1, 1),
                end_month=datetime(2026, 6, 1),
                identity_number="320101199001011234",
                department="第十六分公司",
                name="张三",
                company="南京南化建设有限公司",
                print_group="组1",
            ),
        ),
        attachment_names=(),
        allowed_actions={},
    )
    client.app.state.nocobase_query_service.get_application = lambda _id: detail
    client.app.state.rights_service._run = lambda context, selected, request: {
        "application": detail.code,
        "groups": len(request.groups),
        "upload_to_erp": request.upload_to_erp,
    }
    try:
        response = client.post(
            "/api/v1/nocobase/applications/1001/print",
            json={"account_id": account.id, "upload_to_erp": True},
        )
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        assert wait_until(
            lambda: coordinator.get(task_id).status is TaskStatus.SUCCEEDED
        )
        assert coordinator.get(task_id).result == {
            "application": detail.code,
            "groups": 1,
            "upload_to_erp": True,
        }
    finally:
        coordinator.close()
