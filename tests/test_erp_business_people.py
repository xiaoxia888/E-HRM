from __future__ import annotations

import logging
import json
from pathlib import Path

import pytest

from ehrm.core.exceptions import AiResponseInvalidError, ErpQueryFailedError
from ehrm.core.settings import load_settings
from ehrm.modules.ai.business_classification import BusinessIntent
from ehrm.modules.ai.business_people import validate_business_people_payload
from ehrm.modules.ai.client import OllamaTaskExtractionClient
from ehrm.modules.ai.models import ReasoningMode
from ehrm.modules.erp.business_people_service import ErpBusinessPeopleService
from ehrm.modules.erp.models import ErpPersonRecord, ErpTaskRecord


def _record(title: str, description: str = "") -> ErpTaskRecord:
    return ErpTaskRecord(
        id="erp-1",
        code="RLSQ-001",
        initiated_date="2026-09-29",
        title=title,
        description=description,
        transaction_type="社保咨询",
        status="50",
        originator="申请人",
        department="申请部门",
    )


def _person(name: str, identity: str, *, company: str = "甲公司") -> ErpPersonRecord:
    return ErpPersonRecord(
        id=identity,
        employee_code="E-1",
        name=name,
        identity_number=identity,
        company=company,
        department="项目部",
        status="在职",
        is_quit="否",
    )


def _model_people(record: ErpTaskRecord, name: str, identity: str = ""):
    evidence = f"{name} {identity}".strip()
    return validate_business_people_payload(
        {"people": [{"name": name, "identity_number": identity, "evidence": evidence}]},
        record,
    )


class _AiClient:
    def __init__(self, people) -> None:
        self.people = people

    def extract_business_people(self, record, intent, reasoning_mode):
        return self.people


class _Lookup:
    def __init__(self, *, by_identity=None, by_name=None) -> None:
        self.by_identity = by_identity or {}
        self.by_name = by_name or {}

    def lookup_people(self, *, identity_numbers=(), names=()):
        return (
            {identity: self.by_identity.get(identity, ()) for identity in identity_numbers},
            {name: self.by_name.get(name, ()) for name in names},
        )


def _service(tmp_path: Path, people, lookup: _Lookup) -> ErpBusinessPeopleService:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    return ErpBusinessPeopleService(
        settings,
        logging.getLogger("test.erp.business_people"),
        ai_client=_AiClient(people),
        person_lookup=lookup,
    )


def test_explicit_identity_enriches_enrollment_person(tmp_path: Path) -> None:
    identity = "142725199612061613"
    record = _record("请为苏兆瑞办理参保", f"苏兆瑞 {identity} 从10月开始缴纳社保")
    people = _model_people(record, "苏兆瑞", identity)
    lookup = _Lookup(by_identity={identity: (_person("苏兆瑞", identity),)})

    result = _service(tmp_path, people, lookup).extract(
        record, BusinessIntent.EMPLOYMENT_ENROLLMENT
    )

    assert result.people[0].name == "苏兆瑞"
    assert result.people[0].identity_number == identity
    assert result.people[0].company == "甲公司"
    assert result.people[0].department == "项目部"
    assert result.people[0].match_status == "matched_by_identity"
    assert result.issues == ()


def test_explicit_identity_not_found_is_preserved_and_reported(tmp_path: Path) -> None:
    identity = "142725199612061613"
    record = _record(f"停缴苏兆瑞 {identity} 的社保")
    result = _service(
        tmp_path, _model_people(record, "苏兆瑞", identity), _Lookup()
    ).extract(record, BusinessIntent.EMPLOYMENT_TERMINATION)

    assert result.people[0].identity_number == identity
    assert result.people[0].company == ""
    assert result.people[0].department == ""
    assert result.people[0].match_status == "not_found"
    assert result.issues[0].code == "ERP_PERSON_NOT_FOUND"
    assert result.needs_review is True


def test_duplicate_name_returns_only_name_and_error(tmp_path: Path) -> None:
    record = _record("关于赵佳男停缴社保事宜")
    first = _person("赵佳男", "320482198706114614")
    second = _person("赵佳男", "142725199612061613", company="乙公司")
    result = _service(
        tmp_path,
        _model_people(record, "赵佳男"),
        _Lookup(by_name={"赵佳男": (first, second)}),
    ).extract(record, BusinessIntent.EMPLOYMENT_TERMINATION)

    assert result.people[0].name == "赵佳男"
    assert result.people[0].identity_number == ""
    assert result.people[0].company == ""
    assert result.people[0].department == ""
    assert result.people[0].match_status == "ambiguous"
    assert result.issues[0].code == "ERP_PERSON_AMBIGUOUS"
    assert "320482198706114614" not in str(result.as_dict())
    assert "142725199612061613" not in str(result.as_dict())


def test_unique_name_enriches_termination_person(tmp_path: Path) -> None:
    record = _record("关于赵佳男停缴社保事宜")
    identity = "320482198706114614"
    result = _service(
        tmp_path,
        _model_people(record, "赵佳男"),
        _Lookup(by_name={"赵佳男": (_person("赵佳男", identity),)}),
    ).extract(record, BusinessIntent.EMPLOYMENT_TERMINATION)

    assert result.people[0].identity_number == identity
    assert result.people[0].company == "甲公司"
    assert result.people[0].match_status == "matched_by_name"
    assert result.issues == ()


def test_name_match_with_invalid_erp_identity_is_reported(tmp_path: Path) -> None:
    record = _record("关于赵佳男停缴社保事宜")
    result = _service(
        tmp_path,
        _model_people(record, "赵佳男"),
        _Lookup(by_name={"赵佳男": (_person("赵佳男", ""),)}),
    ).extract(record, BusinessIntent.EMPLOYMENT_TERMINATION)

    assert result.people[0].identity_number == ""
    assert result.people[0].company == ""
    assert result.issues[0].code == "ERP_PERSON_IDENTITY_INVALID"


def test_identity_name_mismatch_keeps_source_identity_without_enrichment(tmp_path: Path) -> None:
    identity = "142725199612061613"
    record = _record(f"停缴苏兆瑞 {identity} 的社保")
    result = _service(
        tmp_path,
        _model_people(record, "苏兆瑞", identity),
        _Lookup(by_identity={identity: (_person("其他人", identity),)}),
    ).extract(record, BusinessIntent.EMPLOYMENT_TERMINATION)

    assert result.people[0].identity_number == identity
    assert result.people[0].company == ""
    assert result.issues[0].code == "ERP_PERSON_IDENTITY_NAME_MISMATCH"


def test_no_named_person_returns_review_issue(tmp_path: Path) -> None:
    record = _record("为五位新员工办理参保")
    people = validate_business_people_payload({"people": []}, record)
    result = _service(tmp_path, people, _Lookup()).extract(
        record, BusinessIntent.EMPLOYMENT_ENROLLMENT
    )

    assert result.people == ()
    assert result.issues[0].code == "AI_NO_PERSON_EXTRACTED"


def test_person_database_failure_remains_in_task_result(tmp_path: Path) -> None:
    record = _record("关于赵佳男停缴社保事宜")

    class BrokenLookup:
        def lookup_people(self, *, identity_numbers=(), names=()):
            raise ErpQueryFailedError("ERP 人员数据库连接失败")

    result = _service(
        tmp_path, _model_people(record, "赵佳男"), BrokenLookup()
    ).extract(record, BusinessIntent.EMPLOYMENT_TERMINATION)

    assert result.people[0].name == "赵佳男"
    assert result.people[0].identity_number == ""
    assert result.issues[0].code == "ERP_QUERY_FAILED"
    assert result.needs_review is True


def test_model_identity_must_be_in_its_source_evidence() -> None:
    record = _record("为苏兆瑞办理参保", "另外有身份证号 142725199612061613")
    with pytest.raises(AiResponseInvalidError, match="身份证.*依据"):
        validate_business_people_payload(
            {
                "people": [
                    {"name": "苏兆瑞", "identity_number": "142725199612061613", "evidence": "苏兆瑞"}
                ]
            },
            record,
        )


def test_model_name_must_appear_in_application() -> None:
    with pytest.raises(AiResponseInvalidError, match="姓名.*原文"):
        validate_business_people_payload(
            {"people": [{"name": "苏兆瑞", "identity_number": "", "evidence": "苏兆瑞"}]},
            _record("为五位新员工办理参保"),
        )


@pytest.mark.parametrize(
    ("intent", "prompt_phrase"),
    [
        (BusinessIntent.EMPLOYMENT_ENROLLMENT, "参保人员"),
        (BusinessIntent.EMPLOYMENT_TERMINATION, "停保人员"),
    ],
)
def test_ai_uses_business_specific_prompt_and_full_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    intent: BusinessIntent,
    prompt_phrase: str,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    client = OllamaTaskExtractionClient(settings.ai, logging.getLogger("test.ai.people"))
    record = _record("请办理苏兆瑞的社保", "苏兆瑞 142725199612061613")
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, *, payload: dict, operation: str) -> dict:
        captured.update({"method": method, "payload": payload})
        return {
            "message": {
                "content": json.dumps({
                    "people": [{
                        "name": "苏兆瑞",
                        "identity_number": "142725199612061613",
                        "evidence": "苏兆瑞 142725199612061613",
                    }]
                }, ensure_ascii=False)
            }
        }

    monkeypatch.setattr(client, "_request_json", fake_request)
    result = client.extract_business_people(record, intent, ReasoningMode.OFF)

    assert result.people[0].identity_number == "142725199612061613"
    assert captured["method"] == "POST"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert prompt_phrase in payload["messages"][0]["content"]
    assert json.loads(payload["messages"][1]["content"]) == {
        "application_date": "2026-09-29",
        "title_summary": "请办理苏兆瑞的社保",
        "request_details": "苏兆瑞 142725199612061613",
    }
    assert payload["format"]["required"] == ["people"]
