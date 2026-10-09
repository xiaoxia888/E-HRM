from __future__ import annotations

from datetime import date
import logging
from pathlib import Path
from types import SimpleNamespace

from ehrm.core.settings import load_settings
from ehrm.modules.ai.business_classification import BusinessClassification
from ehrm.modules.ai.models import ExtractedPerson, ExtractedPrintGroup, TaskExtraction
from ehrm.modules.erp.business_people_service import (
    BusinessPeopleResult,
    BusinessPerson,
    BusinessPersonIssue,
)
from ehrm.modules.erp.models import ErpTaskRecord
from ehrm.web.nocobase_form_analysis import NocoBaseFormAnalysisService


def _record(title: str = "请办理社保") -> ErpTaskRecord:
    return ErpTaskRecord(
        id="erp-1", code="RLSQ-001", initiated_date="2026-09-29",
        title=title, description="请处理相关人员", transaction_type="社保咨询",
        status="", originator="", department="",
    )


class _Ai:
    def __init__(self, business_type: str, *, classified: bool = True, extraction=None):
        self.decision = BusinessClassification(
            business_type=business_type,
            source_transaction_type="社保咨询",
            classified=classified,
            evidence="明确申请办理" if classified else "",
            reason="申请意图不明确" if not classified else "",
        )
        self.extraction = extraction

    def classify(self, record, mode):
        return self.decision

    def extract(self, record, mode):
        return SimpleNamespace(extraction=self.extraction)


class _People:
    def __init__(self, result: BusinessPeopleResult):
        self.result = result

    def extract(self, record, intent, mode):
        return self.result

    def resolve_people(self, record, extraction, intent):
        return self.result


def _service(tmp_path: Path, ai: _Ai, people: _People | None = None):
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    return NocoBaseFormAnalysisService(
        settings,
        logging.getLogger("test.nocobase.form.analysis"),
        ai_client=ai,
        people_service=people,
        today=lambda: date(2026, 9, 30),
    )


def test_unclear_type_returns_reason_without_people_or_form_changes(tmp_path: Path) -> None:
    result = _service(tmp_path, _Ai("社保咨询", classified=False)).analyze(_record())

    assert result["classification"]["classified"] is False
    assert result["people"] == []
    assert result["form_values"] == {}
    assert result["issues"][0]["code"] == "BUSINESS_TYPE_UNCLEAR"


def test_enrollment_maps_people_and_defaults_without_salary_or_household(tmp_path: Path) -> None:
    person = BusinessPerson(
        "苏兆瑞", "142725199612061613", "甲公司", "工程部", "E001",
        "matched_by_identity", "13800138000",
    )
    people = _People(BusinessPeopleResult("RLSQ-001", "employment_enrollment", (person,), ()))
    result = _service(tmp_path, _Ai("用工参保登记"), people).analyze(_record())

    assert result["form_values"]["prob_type"] == "social_security_enrollment"
    row = result["form_values"]["insurance_person"][0]
    assert row["user_name"] == "苏兆瑞"
    assert row["id_card_no"] == "142725199612061613"
    assert row["phone"] == "13800138000"
    assert row["contract_add_reason"] == "新签"
    assert row["contract_start_date"] == "2026-09-30"
    assert row["contract_end_date"] == "2029-09-30"
    assert row["insurance_identity"] == "企业职工"
    assert "monthly_contribution_salary" not in row
    assert "is_technology" not in row
    assert "household_type" not in row
    assert "administrative_division_id" not in row


def test_termination_preserves_ambiguous_person_and_issue(tmp_path: Path) -> None:
    people = _People(BusinessPeopleResult(
        "RLSQ-001", "employment_termination",
        (BusinessPerson("张伟", match_status="ambiguous"),),
        (BusinessPersonIssue("ERP_PERSON_AMBIGUOUS", "张伟", "存在重名，请人工核对"),),
    ))
    result = _service(tmp_path, _Ai("退工停保登记"), people).analyze(_record())

    assert result["form_values"]["prob_type"] == "social_security_termination"
    assert result["form_values"]["termination_person"] == [
        {"user_name": "张伟", "id_card_no": ""}
    ]
    assert result["needs_review"] is True
    assert result["issues"][0]["code"] == "ERP_PERSON_AMBIGUOUS"


def test_identity_name_mismatch_is_not_written_into_nocobase(tmp_path: Path) -> None:
    people = _People(BusinessPeopleResult(
        "RLSQ-001", "employment_termination",
        (BusinessPerson("张伟", "320482198706114614", match_status="name_mismatch"),),
        (BusinessPersonIssue("ERP_PERSON_IDENTITY_NAME_MISMATCH", "张伟", "姓名和身份证不匹配"),),
    ))
    result = _service(tmp_path, _Ai("退工停保登记"), people).analyze(_record())

    assert result["form_values"]["termination_person"][0]["id_card_no"] == ""
    assert result["needs_review"] is True


def test_rights_maps_group_and_months_to_related_persons(tmp_path: Path) -> None:
    extraction = TaskExtraction(
        groups=(ExtractedPrintGroup(
            print_mode="individual", insurance_type="养老", start_month="2026-07",
            end_month="2026-09", time_expression="最近三个月",
            date_basis="explicit_range", relative_month_count=None,
            evidence="社保证明", people=(ExtractedPerson("董健", "董健", 1.0),),
            needs_review=False, review_reasons=(), warnings=(),
        ),),
        needs_review=False, review_reasons=(), warnings=(),
    )
    people = _People(BusinessPeopleResult(
        "RLSQ-001", "rights_statement",
        (BusinessPerson("董健", "341125199908201295", "甲公司", "技术中心"),), (),
    ))
    result = _service(tmp_path, _Ai("单位社保权益单", extraction=extraction), people).analyze(_record())

    assert result["form_values"]["prob_type"] == "social_security_rights"
    assert result["form_values"]["related_persons"] == [{
        "user_name": "董健", "id_card_no": "341125199908201295",
        "company": "甲公司", "dept_name": "技术中心", "print_group": "组1",
        "insurance_type": "elderly_care", "start_month": "2026-07-01",
        "end_month": "2026-09-01",
    }]


def test_rights_individual_print_mode_assigns_distinct_groups(tmp_path: Path) -> None:
    extraction = TaskExtraction(
        groups=(ExtractedPrintGroup(
            print_mode="individual", insurance_type="养老", start_month="2026-07",
            end_month="2026-09", time_expression="最近三个月",
            date_basis="explicit_range", relative_month_count=None,
            evidence="分别开具社保证明", people=(
                ExtractedPerson("董健", "董健", 1.0),
                ExtractedPerson("张权", "张权", 1.0),
            ), needs_review=False, review_reasons=(), warnings=(),
        ),), needs_review=False, review_reasons=(), warnings=(),
    )
    people = _People(BusinessPeopleResult(
        "RLSQ-001", "rights_statement",
        (BusinessPerson("董健"), BusinessPerson("张权")), (),
    ))

    result = _service(tmp_path, _Ai("单位社保权益单", extraction=extraction), people).analyze(_record())

    assert [row["print_group"] for row in result["form_values"]["related_persons"]] == [
        "组1", "组2",
    ]


def test_rights_review_flag_is_preserved_without_specific_reason(tmp_path: Path) -> None:
    extraction = TaskExtraction(
        groups=(ExtractedPrintGroup(
            print_mode=None, insurance_type="养老", start_month="2026-07",
            end_month="2026-09", time_expression="最近三个月",
            date_basis="explicit_range", relative_month_count=None,
            evidence="社保证明", people=(ExtractedPerson("董健", "董健", 1.0),),
            needs_review=True, review_reasons=(), warnings=(),
        ),), needs_review=True, review_reasons=(), warnings=(),
    )
    people = _People(BusinessPeopleResult(
        "RLSQ-001", "rights_statement", (BusinessPerson("董健"),), (),
    ))

    result = _service(tmp_path, _Ai("单位社保权益单", extraction=extraction), people).analyze(_record())

    assert result["needs_review"] is True
    assert result["issues"]
