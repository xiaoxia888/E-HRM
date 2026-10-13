import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Error as PlaywrightError

from ehrm.core.settings import load_settings
from ehrm.modules.nocobase.exceptions import NocoBaseInvalidTokenError, NocoBaseRequestError
from ehrm.modules.nocobase.rights_application_client import (
    NocoBaseRightsApplicationClient,
)


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.disposed = False

    def json(self) -> object:
        return self.payload

    def dispose(self) -> None:
        self.disposed = True


class FakeRequest:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.response


class FailingRequest:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        raise PlaywrightError(f"APIRequestContext.get: {self.reason}\nAuthorization: Bearer secret-token")


def _payload() -> dict[str, object]:
    return {
        "data": [
            {
                "initiation_date": "2026-09-02T07:16:53.980Z",
                "actual_date": None,
                "estimate_date": None,
                "title": "测试社保权益单申请2",
                "id": 384427705696256,
                "estimate_time": 0,
                "code": "RLSQ20260902-0002",
                "actual_time": 0,
                "status": "NEW",
                "initiator_id": 25,
                "prob_type": "social_security_rights",
                "initiator_name": {
                    "nickname": "夏国玺",
                    "username": "xiaguoxi",
                    "id": 25,
                },
            }
        ],
        "meta": {
            "count": 1,
            "page": 1,
            "pageSize": 20,
            "totalPage": 1,
            "allowedActions": {
                "view": [384427705696256],
                "update": [384427705696256],
                "destroy": [384427705696256],
            },
        },
    }


def test_list_applications_builds_query_and_parses_page(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    response = FakeResponse(_payload())
    request = FakeRequest(response)
    client = NocoBaseRightsApplicationClient(
        settings.nocobase,
        request,  # type: ignore[arg-type]
        logging.getLogger("test.nocobase-rights-applications"),
    )

    result = client.list_applications(
        "authorization-token",
        page=1,
        page_size=20,
    )

    assert result.meta.count == 1
    assert result.meta.total_page == 1
    assert result.meta.allowed_actions["view"] == (384427705696256,)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.application_id == 384427705696256
    assert record.code == "RLSQ20260902-0002"
    assert record.status == "NEW"
    assert record.initiator_name == "夏国玺"
    assert record.initiation_date is not None
    assert record.actual_date is None

    url, call = request.calls[0]
    assert url == (
        settings.nocobase.base_url
        + settings.nocobase.rights_application_list_path
    )
    assert call["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer authorization-token",
    }
    params = call["params"]
    assert isinstance(params, dict)
    assert json.loads(params["filter"])["$and"][0]["$and"][0] == {
        "prob_type": {"$in": ["social_security_rights", "social_security_enrollment", "social_security_termination", "medical_enrollment", "medical_termination"]}
    }
    assert params["appends[]"] == "initiator_name"
    assert params["page"] == "1"
    assert params["pageSize"] == "20"
    assert params["tree"] == "false"
    assert response.disposed


def test_list_applications_forwards_invalid_token_for_session_retry(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    response = FakeResponse(
        {
            "errors": [
                {
                    "message": "Your session has expired. Please sign in again.",
                    "code": "INVALID_TOKEN",
                }
            ]
        }
    )
    client = NocoBaseRightsApplicationClient(
        settings.nocobase,
        FakeRequest(response),  # type: ignore[arg-type]
        logging.getLogger("test.nocobase-rights-invalid-token"),
    )

    with pytest.raises(NocoBaseInvalidTokenError, match="session has expired"):
        client.list_applications("expired-token", page=1, page_size=20)

    assert response.disposed


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("getaddrinfo ENOTFOUND cloud.njncc.com", "无法解析 NocoBase 域名 cloud.njncc.com"),
        ("Request timed out after 15000ms", "连接 NocoBase 超时"),
        ("Timeout 15000ms exceeded", "连接 NocoBase 超时"),
        ("connect ECONNREFUSED", "无法连接 NocoBase 服务器 cloud.njncc.com"),
    ],
)
def test_list_applications_explains_transport_errors_without_leaking_key(
    tmp_path: Path, reason: str, expected: str,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    client = NocoBaseRightsApplicationClient(
        settings.nocobase,
        FailingRequest(reason),  # type: ignore[arg-type]
        logging.getLogger("test.nocobase-rights-network"),
    )

    with pytest.raises(NocoBaseRequestError) as caught:
        client.list_applications("secret-token", page=1, page_size=20)

    assert expected in caught.value.message
    assert "secret-token" not in caught.value.message
    assert "secret-token" not in (caught.value.details or "")
    assert "[已隐藏]" in (caught.value.details or "")


def test_get_application_builds_query_and_parses_detail(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    response = FakeResponse(
        {
            "data": {
                "createdAt": "2026-09-02T07:16:54.111Z",
                "initiation_date": "2026-09-02T07:16:53.980Z",
                "actual_date": None,
                "estimate_date": None,
                "title": "测试社保权益单申请2",
                "id": 384427705696256,
                "estimate_time": 0,
                "problem_desc": None,
                "code": "RLSQ20260902-0002",
                "actual_time": 0,
                "status": "NEW",
                "handling_method": None,
                "prob_type": "social_security_rights",
                "createdBy": {"nickname": "夏国玺"},
                "initiator_name": {"nickname": "夏国玺"},
                "related_persons": [
                    {
                        "id": 384427705696257,
                        "status": "NEW",
                        "insurance_type": "elderly_care",
                        "start_month": "2025-05-01",
                        "end_month": "2026-01-01",
                        "id_card_no": "410423199005124058",
                            "dept_name": "第十六分公司",
                            "user_name": "王明明",
                        "company": "南京南化建设有限公司",
                        "print_group": "组1",
                    }
                ],
                "attachments": [],
            },
            "meta": {
                "allowedActions": {"view": [384427705696256]},
            },
        }
    )
    request = FakeRequest(response)
    client = NocoBaseRightsApplicationClient(
        settings.nocobase,
        request,  # type: ignore[arg-type]
        logging.getLogger("test.nocobase-rights-application-detail"),
    )

    detail = client.get_application("authorization-token", 384427705696256)

    assert detail.application_id == 384427705696256
    assert detail.created_by_name == "夏国玺"
    assert detail.initiator_name == "夏国玺"
    assert detail.allowed_actions["view"] == (384427705696256,)
    assert len(detail.related_persons) == 1
    person = detail.related_persons[0]
    assert person.insurance_type == "elderly_care"
    assert person.identity_number == "410423199005124058"
    assert person.print_group == "组1"
    assert person.name == "王明明"
    assert person.department == "第十六分公司"
    assert person.start_month is not None

    url, call = request.calls[0]
    parsed = urlsplit(url)
    assert parsed.path == settings.nocobase.rights_application_detail_path
    assert parse_qs(parsed.query) == {
        "appends[]": [
            "createdBy",
            "initiator_name",
            "related_persons",
            "attachments",
            "insurance_person",
            "termination_person",
            "termination_person.createdBy",
            "med_ins_withdrawal_record",
            "med_ins_enrollee",
        ],
        "filterByTk": ["384427705696256"],
    }
    assert call["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer authorization-token",
    }
    assert response.disposed


def test_medical_application_detail_uses_confirmed_association_names(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    response = FakeResponse({"data": {
        "id": 1, "prob_type": "medical_termination", "code": "MED-001",
        "med_ins_withdrawal_record": [{
            "id": 11, "user_name": "测试甲", "id_card_no": "123456789012345678",
            "med_ins_stop_reason": "在职人员解除/终止劳动合同",
            "med_stop_date": "2026-10-12", "med_ins_stop_month_fee": "否",
        }],
        "med_ins_enrollee": [{
            "id": 12, "user_name": "测试乙", "id_card_no": "123456789012345679",
            "ethnicity": "汉族", "phone": "13800000000", "arrive_unit_time": "2026-10-12",
        }],
    }})
    client = NocoBaseRightsApplicationClient(
        settings.nocobase, FakeRequest(response), logging.getLogger("test.medical-associations"),
    )
    detail = client.get_application("authorization-token", 1)
    assert detail.med_ins_withdrawal_record[0]["med_ins_stop_month_fee"] == "否"
    assert detail.med_ins_enrollee[0]["phone"] == "13800000000"
    assert response.disposed
