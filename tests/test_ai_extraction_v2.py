from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ehrm.core.exceptions import (
    AiResponseInvalidError,
    MedicalInsuranceUnsupportedError,
)
from ehrm.core.settings import load_settings
from ehrm.modules.ai.client import OllamaTaskExtractionClient
from ehrm.modules.ai.models import ReasoningMode
from ehrm.modules.ai.normalizer import normalize_semantic_extraction
from ehrm.modules.ai.v2_models import validate_semantic_extraction_payload
from ehrm.modules.erp.models import ErpTaskRecord


def _person(
    name: str,
    *,
    identity: str | None = None,
    birth_year_hint: int | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "social_security_number": identity,
        "birth_year_hint": birth_year_hint,
    }


def _time(
    time_type: str,
    expression: str,
    *,
    start_month: str | None = None,
    end_month: str | None = None,
    month_count: int | None = None,
) -> dict[str, object]:
    return {
        "type": time_type,
        "expression": expression,
        "start_month": start_month,
        "end_month": end_month,
        "month_count": month_count,
    }


def _rights_request(
    source_text: str,
    people: list[dict[str, object]],
    time: dict[str, object],
    *,
    benefit_category: str = "社保",
    print_mode: str | None = None,
) -> dict[str, object]:
    return {
        "type": "rights_statement",
        "source_text": source_text,
        "reason": "",
        "print_plan": {
            "people": people,
            "benefit_category": benefit_category,
            "print_mode": print_mode,
            "time": time,
        },
    }


def _record(
    *,
    title: str,
    description: str,
    application_date: str = "2026-06-26",
) -> ErpTaskRecord:
    return ErpTaskRecord(
        id="erp-id",
        code="RLSQ-V2",
        initiated_date=application_date,
        title=title,
        description=description,
        transaction_type="社保咨询",
        status="50",
        originator="申请人",
        department="技术中心",
    )


def test_v2_normalizer_removes_incomplete_title_summary_group() -> None:
    title = "仪征TPV项目人员（付劲松）社保查询"
    detail = (
        "仪征高端TPV项目办理施工许可证需要相关人员社保，"
        "请帮忙下载付劲松社保缴纳相关证明文件，"
        "缴纳时间为2026年4月-2026年6月"
    )
    payload = {
        "requests": [
            _rights_request(
                title,
                [_person("付劲松")],
                _time("missing", ""),
            ),
            _rights_request(
                detail,
                [_person("付劲松")],
                _time(
                    "explicit_range",
                    "2026年4月-2026年6月",
                    start_month="2026-04",
                    end_month="2026-06",
                ),
            ),
        ]
    }

    result = normalize_semantic_extraction(
        validate_semantic_extraction_payload(payload),
        _record(title=title, description=detail),
    )

    assert len(result.requirements) == 1
    assert len(result.groups) == 1
    assert result.groups[0].start_month == "2026-04"
    assert result.groups[0].end_month == "2026-06"
    assert result.needs_review is False


def test_v2_normalizer_calculates_relative_months_and_keeps_person_binding() -> None:
    payload = {
        "requests": [
            _rights_request(
                "刘涛3年",
                [_person("刘涛")],
                _time("relative_months", "3年", month_count=36),
            ),
            _rights_request(
                "吴增光1年",
                [_person("吴增光")],
                _time("relative_months", "1年", month_count=12),
            ),
        ]
    }

    result = normalize_semantic_extraction(
        validate_semantic_extraction_payload(payload),
        _record(
            title="投标人员社保证明：刘涛3年、吴增光1年",
            description="",
            application_date="2026-07-02",
        ),
    )

    assert [[person.name for person in group.people] for group in result.groups] == [
        ["刘涛"],
        ["吴增光"],
    ]
    assert (result.groups[0].start_month, result.groups[0].end_month) == (
        "2023-07",
        "2026-06",
    )
    assert (result.groups[1].start_month, result.groups[1].end_month) == (
        "2025-07",
        "2026-06",
    )


def test_v2_normalizer_derives_defaults_and_review_state() -> None:
    payload = {
        "requests": [
            _rights_request(
                "张三、李四近一年社保",
                [_person("张三"), _person("李四")],
                _time("relative_months", "近一年", month_count=12),
            )
        ]
    }

    result = normalize_semantic_extraction(
        validate_semantic_extraction_payload(payload),
        _record(
            title="张三、李四近一年社保",
            description="",
            application_date="2026-08-20",
        ),
    )

    group = result.groups[0]
    assert group.insurance_type == "养老"
    assert group.print_mode is None
    assert group.needs_review is True
    assert group.review_reasons == (
        "原文未说明多人合并打印还是每人单独打印",
    )
    assert result.needs_review is True


def test_v2_normalizer_rejects_medical_insurance_as_temporarily_unsupported() -> None:
    payload = {
        "requests": [
            _rights_request(
                "查询施瀛博8月医保权益单",
                [_person("施瀛博")],
                _time(
                    "explicit_month",
                    "8月",
                    start_month="2026-08",
                    end_month="2026-08",
                ),
                benefit_category="医保",
            )
        ]
    }

    with pytest.raises(
        MedicalInsuranceUnsupportedError,
        match="当前版本暂不支持医保权益单",
    ):
        normalize_semantic_extraction(
            validate_semantic_extraction_payload(payload),
            _record(
                title="查询施瀛博8月医保权益单",
                description="",
                application_date="2026-08-18",
            ),
        )


def test_v2_repeated_people_in_explicit_print_groups_do_not_require_review() -> None:
    payload = {
        "requests": [
            _rights_request(
                "主要人员：张三、李四2人打印1张，1年社保",
                [_person("张三"), _person("李四")],
                _time("relative_months", "1年", month_count=12),
                print_mode="combined",
            ),
            _rights_request(
                "全体人员：张三、李四、王五3人另打1张，1年社保",
                [_person("张三"), _person("李四"), _person("王五")],
                _time("relative_months", "1年", month_count=12),
                print_mode="combined",
            ),
        ]
    }

    result = normalize_semantic_extraction(
        validate_semantic_extraction_payload(payload),
        _record(
            title="项目投标人员社保打印",
            description=(
                "主要人员：张三、李四2人打印1张，1年社保；"
                "全体人员：张三、李四、王五3人另打1张，1年社保"
            ),
            application_date="2026-08-24",
        ),
    )

    assert len(result.groups) == 2
    assert result.needs_review is False
    assert all(group.needs_review is False for group in result.groups)
    assert [person.name for person in result.groups[0].people] == ["张三", "李四"]
    assert [person.name for person in result.groups[1].people] == [
        "张三",
        "李四",
        "王五",
    ]


def test_v2_non_print_request_becomes_warning_without_blocking_print_group() -> None:
    payload = {
        "requests": [
            {
                "type": "statistics",
                "source_text": "公司参保总人数",
                "reason": "统计需求，不是具体人员权益单",
                "print_plan": None,
            },
            _rights_request(
                "吴朝彬近一年社保清单",
                [_person("吴朝彬")],
                _time("relative_months", "近一年", month_count=12),
            ),
        ]
    }

    result = normalize_semantic_extraction(
        validate_semantic_extraction_payload(payload),
        _record(
            title="公司参保总人数及吴朝彬近一年社保清单",
            description="",
        ),
    )

    assert len(result.groups) == 1
    assert result.needs_review is False
    assert len(result.warnings) == 1
    assert "公司参保总人数" in result.warnings[0]


def test_v2_schema_rejects_model_owned_review_fields() -> None:
    request = _rights_request(
        "张三近一年社保",
        [_person("张三")],
        _time("relative_months", "近一年", month_count=12),
    )
    request["needs_review"] = False

    with pytest.raises(AiResponseInvalidError, match="字段不正确"):
        validate_semantic_extraction_payload({"requests": [request]})


def test_ollama_client_parses_v2_and_returns_existing_domain_model(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    client = OllamaTaskExtractionClient(
        settings.ai,
        logging.getLogger("test.ai.v2.client"),
    )
    semantic_payload = {
        "requests": [
            _rights_request(
                "付劲松社保缴纳证明，缴纳时间为2026年4月-2026年6月",
                [_person("付劲松")],
                _time(
                    "explicit_range",
                    "2026年4月-2026年6月",
                    start_month="2026-04",
                    end_month="2026-06",
                ),
            )
        ]
    }
    response_payload = {
        "model": "qwen3.5:9b",
        "message": {"content": json.dumps(semantic_payload, ensure_ascii=False)},
        "done_reason": "stop",
        "total_duration": 1,
        "prompt_eval_count": 10,
        "eval_count": 20,
    }
    record = _record(
        title="仪征TPV项目人员（付劲松）社保查询",
        description=(
            "请下载付劲松社保缴纳证明，缴纳时间为2026年4月-2026年6月"
        ),
    )

    response = client._parse_response(
        response_payload,
        ReasoningMode.OFF,
        record=record,
    )

    assert response.extraction.groups[0].people[0].name == "付劲松"
    assert response.extraction.groups[0].start_month == "2026-04"
    assert response.extraction.needs_review is False
