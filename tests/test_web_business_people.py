from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from ehrm.core.settings import load_settings
from ehrm.modules.ai.business_classification import BusinessIntent
from ehrm.modules.erp.business_people_service import (
    BusinessPeopleResult,
    BusinessPerson,
    BusinessPersonIssue,
)
from ehrm.web.app import create_app
from ehrm.web.tasks import TaskCoordinator


@pytest.mark.parametrize(
    ("route", "expected_intent"),
    [
        ("enrollment", BusinessIntent.EMPLOYMENT_ENROLLMENT),
        ("termination", BusinessIntent.EMPLOYMENT_TERMINATION),
    ],
)
def test_business_people_endpoint_returns_people_and_review_issues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    expected_intent: BusinessIntent,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=1)
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    observed: dict[str, object] = {}

    def fake_extract(record, intent, reasoning_mode=None):
        observed.update({"record": record, "intent": intent})
        return BusinessPeopleResult(
            application_code=record.code,
            business_type=intent.value,
            people=(BusinessPerson("赵佳男", match_status="ambiguous"),),
            issues=(BusinessPersonIssue(
                "ERP_PERSON_AMBIGUOUS", "赵佳男", "ERP 人员重名，需人工确认"
            ),),
        )

    monkeypatch.setattr(app.state.erp_business_people_service, "extract", fake_extract)
    try:
        response = TestClient(app).post(
            f"/api/v1/erp/{route}/people-extraction",
            json={
                "application_code": "RLSQ-001",
                "application_date": "2026-09-29",
                "title": "关于赵佳男社保事项",
                "description": "请处理赵佳男",
                "erp_transaction_type": "社保咨询",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["application_code"] == "RLSQ-001"
        assert payload["needs_review"] is True
        assert payload["people"][0]["identity_number"] == ""
        assert payload["issues"][0]["code"] == "ERP_PERSON_AMBIGUOUS"
        assert observed["intent"] == expected_intent
        assert observed["record"].description == "请处理赵佳男"
    finally:
        coordinator.close()


def test_business_people_endpoint_rejects_missing_application_text(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=1)
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    try:
        response = TestClient(app).post(
            "/api/v1/erp/enrollment/people-extraction",
            json={"application_code": "RLSQ-001", "title": "", "description": ""},
        )
        assert response.status_code == 400
        assert "标题" in response.json()["message"]
    finally:
        coordinator.close()


def test_nocobase_form_analysis_accepts_current_form_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=1)
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    observed = {}

    def fake_analyze(record, reasoning_mode=None):
        observed["record"] = record
        return {
            "classification": {"classified": False, "reason": "意图不明"},
            "business_type": "社保咨询", "prob_type": "", "people": [],
            "issues": [{"code": "BUSINESS_TYPE_UNCLEAR", "message": "意图不明"}],
            "needs_review": True, "form_values": {},
        }

    monkeypatch.setattr(app.state.nocobase_form_analysis_service, "analyze", fake_analyze)
    try:
        response = TestClient(app).post(
            "/api/v1/nocobase/form-analysis",
            json={
                "application_code": "",
                "application_date": "2026-09-29",
                "title": "申请社保事项",
                "description": "请处理",
                "erp_transaction_type": "社保咨询",
            },
        )
        assert response.status_code == 200
        assert response.json()["form_values"] == {}
        assert observed["record"].title == "申请社保事项"
        assert observed["record"].transaction_type == "社保咨询"
    finally:
        coordinator.close()


def test_nocobase_form_analysis_rejects_empty_text(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=1)
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    try:
        response = TestClient(app).post(
            "/api/v1/nocobase/form-analysis", json={"title": "", "description": ""},
        )
        assert response.status_code == 400
        assert "标题" in response.json()["message"]
    finally:
        coordinator.close()


def test_nocobase_origin_is_allowed_for_form_analysis_preflight(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=1)
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    try:
        response = TestClient(app).options(
            "/api/v1/nocobase/form-analysis",
            headers={
                "Origin": "http://cloud.njncc.com:443",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://cloud.njncc.com:443"
    finally:
        coordinator.close()
