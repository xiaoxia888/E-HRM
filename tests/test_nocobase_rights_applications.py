import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from ehrm.core.settings import load_settings
from ehrm.modules.nocobase.exceptions import NocoBaseInvalidTokenError
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
        "prob_type": {"$eq": "social_security_rights"}
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
                        "department": "第十六分公司",
                        "name": "王明明",
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
        ],
        "filterByTk": ["384427705696256"],
    }
    assert call["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer authorization-token",
    }
    assert response.disposed
