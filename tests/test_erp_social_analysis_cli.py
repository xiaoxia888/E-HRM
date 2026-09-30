from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ehrm.modules.ai.business_classification import BusinessClassification
from ehrm.modules.erp.business_people_service import (
    BusinessPeopleResult,
    BusinessPerson,
    BusinessPersonIssue,
)
from ehrm.modules.erp.models import ErpTaskQueryResult, ErpTaskRecord


def _record(code: str = "RLSQ-001", *, transaction_type: str = "社保咨询") -> ErpTaskRecord:
    return ErpTaskRecord(
        id=f"id-{code}",
        code=code,
        initiated_date="2026-09-29",
        title="关于赵佳男停缴社保事宜",
        description="请为赵佳男办理停保",
        transaction_type=transaction_type,
        status="50",
        originator="申请人",
        department="部门",
    )


def _query_result(transaction_type: str, records: tuple[ErpTaskRecord, ...]):
    return ErpTaskQueryResult(
        transaction_type=transaction_type,
        records=records,
        total_count=len(records),
        pages_fetched=1,
    )


def _install_common(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    records: tuple[ErpTaskRecord, ...],
    business_type: str,
    classified: bool = True,
) -> None:
    from ehrm.entrypoints import erp_social_analysis_cli as cli

    class FakeQueryService:
        def __init__(self, *args, **kwargs):
            pass

        def query_tasks(self, transaction_type: str, *, application_code: str, page_size: int):
            assert application_code == "RLSQ-001"
            selected = tuple(record for record in records if record.transaction_type == transaction_type)
            return _query_result(transaction_type, selected)

    class FakeClassifier:
        def __init__(self, *args, **kwargs):
            pass

        def ensure_available(self) -> None:
            pass

        def classify(self, record, mode):
            return BusinessClassification(
                business_type=business_type,
                source_transaction_type=record.transaction_type,
                classified=classified,
                evidence="停缴社保" if classified else "",
                reason="用途不明确" if not classified else "",
            )

    monkeypatch.setattr(cli, "application_runtime_root", lambda config: tmp_path)
    monkeypatch.setattr(cli, "configure_logging", lambda path: logging.getLogger("test"))
    monkeypatch.setattr(cli, "ErpTaskQueryService", FakeQueryService)
    monkeypatch.setattr(cli, "OllamaTaskExtractionClient", FakeClassifier)


def test_code_runs_classification_then_termination_people_and_saves_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ehrm.entrypoints import erp_social_analysis_cli as cli

    _install_common(
        monkeypatch,
        tmp_path,
        records=(_record(),),
        business_type="退工停保登记",
    )

    class FakePeopleService:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, record, intent, reasoning_mode):
            return BusinessPeopleResult(
                application_code=record.code,
                business_type=intent.value,
                people=(BusinessPerson("赵佳男", match_status="ambiguous"),),
                issues=(BusinessPersonIssue(
                    "ERP_PERSON_AMBIGUOUS", "赵佳男", "ERP 人员重名，需人工确认"
                ),),
            )

    monkeypatch.setattr(cli, "ErpBusinessPeopleService", FakePeopleService)
    output = tmp_path / "analysis.json"
    exit_code = cli.main(["--code", "RLSQ-001", "--output", str(output)])

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["application"]["code"] == "RLSQ-001"
    assert report["classification"]["business_type"] == "退工停保登记"
    assert report["people"][0]["name"] == "赵佳男"
    assert report["people"][0]["identity_number"] == ""
    assert report["issues"][0]["code"] == "ERP_PERSON_AMBIGUOUS"
    assert report["needs_review"] is True
    assert "退工停保登记" in capsys.readouterr().out


def test_code_runs_existing_rights_extraction_for_rights_people(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ehrm.entrypoints import erp_social_analysis_cli as cli

    record = _record(transaction_type="单位社保权益单")
    _install_common(
        monkeypatch,
        tmp_path,
        records=(record,),
        business_type="单位社保权益单",
    )

    class FakeRightsService:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, transaction_type: str, *, application_code: str, reasoning_mode: str):
            assert transaction_type == "单位社保权益单"
            assert application_code == "RLSQ-001"
            return {
                "tasks": [{"task_number": "RLSQ-001", "parse_status": {"code": "SUCCESS"}}],
                "rights_statement_requests": [{
                    "task_number": "RLSQ-001",
                    "name": "赵佳男",
                    "social_security_number": "320482198706114614",
                    "group_label": "组1",
                    "identity_match": {
                        "code": "SUCCESS",
                        "company": "甲公司",
                        "department": "项目部",
                        "employee_code": "E-1",
                    },
                }],
            }

    monkeypatch.setattr(cli, "ErpTaskExtractionService", FakeRightsService)
    output = tmp_path / "rights.json"
    exit_code = cli.main(["--code", "RLSQ-001", "--output", str(output)])

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["classification"]["business_type"] == "单位社保权益单"
    assert report["people"] == [{
        "name": "赵佳男",
        "identity_number": "320482198706114614",
        "company": "甲公司",
        "department": "项目部",
        "employee_code": "E-1",
        "match_status": "matched",
        "print_group": "组1",
    }]
    assert report["needs_review"] is False


def test_unclear_type_keeps_erp_enum_and_does_not_extract_people(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ehrm.entrypoints import erp_social_analysis_cli as cli

    _install_common(
        monkeypatch,
        tmp_path,
        records=(_record(),),
        business_type="社保咨询",
        classified=False,
    )
    output = tmp_path / "unclear.json"
    exit_code = cli.main(["--code", "RLSQ-001", "--output", str(output)])

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["classification"]["business_type"] == "社保咨询"
    assert report["people"] == []
    assert report["needs_review"] is True


def test_code_must_match_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ehrm.entrypoints import erp_social_analysis_cli as cli

    _install_common(
        monkeypatch,
        tmp_path,
        records=(_record("RLSQ-001-extra"),),
        business_type="退工停保登记",
    )
    assert cli.main(["--code", "RLSQ-001"]) == 2


def test_rights_task_review_without_people_is_visible() -> None:
    from ehrm.entrypoints.erp_social_analysis_cli import _rights_people

    people, issues = _rights_people(
        {
            "tasks": [{
                "task_number": "RLSQ-001",
                "parse_status": {"code": "SUCCESS"},
                "extraction": {
                    "needs_review": True,
                    "review_reasons": ["申请没有说明打印期限"],
                },
            }],
            "rights_statement_requests": [],
        },
        "RLSQ-001",
    )

    assert people == []
    assert issues == [{
        "code": "AI_REVIEW_REQUIRED",
        "person_name": "",
        "message": "申请没有说明打印期限",
    }]


def test_script_requires_application_code() -> None:
    from ehrm.entrypoints.erp_social_analysis_cli import _parser

    with pytest.raises(SystemExit):
        _parser().parse_args([])
