from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ehrm.core.exceptions import AiResponseInvalidError
from ehrm.core.settings import load_settings
from ehrm.modules.ai.models import (
    ExtractedPerson,
    ExtractedPrintGroup,
    ExtractionResponse,
    ModelMetrics,
    ReasoningMode,
    TaskExtraction,
    resolve_relative_month_ranges,
    validate_extraction_payload,
)
from ehrm.modules.erp.extraction_service import ErpTaskExtractionService
from ehrm.modules.erp.models import (
    ErpCredentials,
    ErpPersonRecord,
    ErpTaskQueryResult,
    ErpTaskRecord,
)
from ehrm.modules.erp.person_service import ErpPersonLookupService


def test_reasoning_modes_use_ollama_native_values() -> None:
    assert ReasoningMode.OFF.ollama_think is False
    assert ReasoningMode.LOW.ollama_think == "low"
    assert ReasoningMode.MEDIUM.ollama_think == "medium"
    assert ReasoningMode.MAX.value == "max"
    assert ReasoningMode.MAX.ollama_think == "max"


def test_extraction_payload_is_strictly_validated() -> None:
    result = validate_extraction_payload(
        {
            "requirements": [
                {
                    "sequence": 1,
                    "source_text": "张三需打印近一年社保",
                    "type": "rights_statement",
                    "supported": True,
                    "reason": "",
                }
            ],
            "groups": [
                {
                    "requirement_sequence": 1,
                    "print_mode": "combined",
                    "insurance_type": "养老",
                    "start_month": "2025-08",
                    "end_month": "2026-07",
                    "time_expression": "近一年",
                    "date_basis": "relative_months",
                    "relative_month_count": 12,
                    "evidence": "张三需打印近一年社保",
                    "people": [
                        {
                            "name": "张三",
                            "social_security_number": "320101199001011234",
                            "birth_year_hint": 1990,
                            "evidence": "张三需打印",
                            "confidence": 0.96,
                        }
                    ],
                    "needs_review": False,
                    "review_reasons": [],
                    "warnings": [],
                }
            ],
            "needs_review": False,
            "review_reasons": [],
            "warnings": [],
        }
    )

    assert result.groups[0].people[0].name == "张三"
    assert (
        result.groups[0].people[0].social_security_number
        == "320101199001011234"
    )
    assert result.groups[0].end_month == "2026-07"
    assert result.groups[0].people[0].birth_year_hint == 1990


def test_statistics_requirement_is_kept_out_of_print_groups() -> None:
    result = validate_extraction_payload(
        {
            "requirements": [
                {
                    "sequence": 1,
                    "source_text": "公司参保总人数（社保网可查询）",
                    "type": "statistics",
                    "supported": False,
                    "reason": "统计需求，不是具体人员权益单",
                },
                {
                    "sequence": 2,
                    "source_text": "吴朝彬近一年社保清单",
                    "type": "rights_statement",
                    "supported": True,
                    "reason": "",
                },
            ],
            "groups": [
                {
                    "requirement_sequence": 2,
                    "print_mode": None,
                    "insurance_type": "养老",
                    "start_month": None,
                    "end_month": None,
                    "time_expression": "近一年",
                    "date_basis": "relative_months",
                    "relative_month_count": 12,
                    "evidence": "吴朝彬近一年社保清单",
                    "people": [
                        {
                            "name": "吴朝彬",
                            "social_security_number": None,
                            "evidence": "吴朝彬近一年社保清单",
                            "confidence": 0.98,
                        }
                    ],
                    "needs_review": False,
                    "review_reasons": [],
                    "warnings": [],
                }
            ],
            "needs_review": False,
            "review_reasons": [],
            "warnings": ["申请还包含公司参保总人数统计需求，本次不处理"],
        }
    )

    assert [item.requirement_type for item in result.requirements] == [
        "statistics",
        "rights_statement",
    ]
    assert [person.name for person in result.groups[0].people] == ["吴朝彬"]
    assert result.groups[0].requirement_sequence == 2


def test_print_group_cannot_reference_statistics_requirement() -> None:
    payload = {
        "requirements": [
            {
                "sequence": 1,
                "source_text": "公司参保总人数（社保网可查询）",
                "type": "statistics",
                "supported": False,
                "reason": "统计需求，不是具体人员权益单",
            }
        ],
        "groups": [
            {
                "requirement_sequence": 1,
                "print_mode": None,
                "insurance_type": "养老",
                "start_month": None,
                "end_month": None,
                "time_expression": "",
                "date_basis": "missing",
                "relative_month_count": None,
                "evidence": "公司参保总人数（社保网可查询）",
                "people": [
                    {
                        "name": "公司参保总人数",
                        "social_security_number": None,
                        "evidence": "公司参保总人数",
                        "confidence": 0.5,
                    }
                ],
                "needs_review": True,
                "review_reasons": ["不是具体人员"],
                "warnings": [],
            }
        ],
        "needs_review": True,
        "review_reasons": ["不是具体人员"],
        "warnings": [],
    }

    with pytest.raises(AiResponseInvalidError, match="不是人员权益单需求"):
        validate_extraction_payload(payload)


def test_person_must_appear_in_referenced_rights_requirement() -> None:
    payload = {
        "requirements": [
            {
                "sequence": 1,
                "source_text": "公司参保总人数（社保网可查询）",
                "type": "statistics",
                "supported": False,
                "reason": "统计需求，不是具体人员权益单",
            },
            {
                "sequence": 2,
                "source_text": "吴朝彬近一年社保清单",
                "type": "rights_statement",
                "supported": True,
                "reason": "",
            },
        ],
        "groups": [
            {
                "requirement_sequence": 2,
                "print_mode": None,
                "insurance_type": "养老",
                "start_month": None,
                "end_month": None,
                "time_expression": "近一年",
                "date_basis": "relative_months",
                "relative_month_count": 12,
                "evidence": "公司参保总人数",
                "people": [
                    {
                        "name": "公司参保总人数",
                        "social_security_number": None,
                        "evidence": "公司参保总人数",
                        "confidence": 0.5,
                    }
                ],
                "needs_review": True,
                "review_reasons": ["不是具体人员"],
                "warnings": [],
            }
        ],
        "needs_review": True,
        "review_reasons": ["不是具体人员"],
        "warnings": [],
    }

    with pytest.raises(AiResponseInvalidError, match="未出现在其引用"):
        validate_extraction_payload(payload)


def test_duplicate_print_groups_are_rejected() -> None:
    group = {
        "requirement_sequence": 1,
        "print_mode": None,
        "insurance_type": "养老",
        "start_month": "2025-01",
        "end_month": "2026-07",
        "time_expression": "2025年1月到2026年7月",
        "date_basis": "explicit_range",
        "relative_month_count": None,
        "evidence": "需要霍宝秀社保 2025年1月到2026年7月",
        "people": [
            {
                "name": "霍宝秀",
                "social_security_number": None,
                "evidence": "需要霍宝秀社保 2025年1月到2026年7月",
                "confidence": 1.0,
            }
        ],
        "needs_review": False,
        "review_reasons": [],
        "warnings": [],
    }
    payload = {
        "requirements": [
            {
                "sequence": 1,
                "source_text": "需要霍宝秀社保 2025年1月到2026年7月",
                "type": "rights_statement",
                "supported": True,
                "reason": "",
            }
        ],
        "groups": [group, dict(group)],
        "needs_review": False,
        "review_reasons": [],
        "warnings": [],
    }

    with pytest.raises(AiResponseInvalidError, match="完全重复"):
        validate_extraction_payload(payload)


def test_relative_month_range_is_calculated_from_application_date() -> None:
    extraction = validate_extraction_payload(
        {
            "requirements": [
                {
                    "sequence": 1,
                    "source_text": "艾文成近半年社保缴费证明",
                    "type": "rights_statement",
                    "supported": True,
                    "reason": "",
                }
            ],
            "groups": [
                {
                    "requirement_sequence": 1,
                    "print_mode": None,
                    "insurance_type": "养老",
                    "start_month": "2025-10",
                    "end_month": "2026-07",
                    "time_expression": "近半年",
                    "date_basis": "relative_months",
                    "relative_month_count": 6,
                    "evidence": "艾文成近半年社保缴费证明",
                    "people": [
                        {
                            "name": "艾文成",
                            "social_security_number": None,
                            "evidence": "艾文成近半年社保缴费证明",
                            "confidence": 0.98,
                        }
                    ],
                    "needs_review": False,
                    "review_reasons": [],
                    "warnings": [],
                }
            ],
            "needs_review": False,
            "review_reasons": [],
            "warnings": [],
        }
    )

    resolved = resolve_relative_month_ranges(extraction, "2026-08-17")

    group = resolved.groups[0]
    assert group.relative_month_count == 6
    assert group.start_month == "2026-02"
    assert group.end_month == "2026-07"
    assert not group.needs_review
    assert group.warnings == (
        "模型返回的相对起止月份已由程序纠正："
        "2025-10 至 2026-07 → 2026-02 至 2026-07",
    )


def test_relative_month_count_conflict_is_corrected_and_marked_for_review() -> None:
    extraction = validate_extraction_payload(
        {
            "requirements": [
                {
                    "sequence": 1,
                    "source_text": "艾文成近半年社保缴费证明",
                    "type": "rights_statement",
                    "supported": True,
                    "reason": "",
                }
            ],
            "groups": [
                {
                    "requirement_sequence": 1,
                    "print_mode": None,
                    "insurance_type": "养老",
                    "start_month": None,
                    "end_month": None,
                    "time_expression": "近半年",
                    "date_basis": "relative_months",
                    "relative_month_count": 10,
                    "evidence": "艾文成近半年社保缴费证明",
                    "people": [
                        {
                            "name": "艾文成",
                            "social_security_number": None,
                            "evidence": "艾文成近半年社保缴费证明",
                            "confidence": 0.98,
                        }
                    ],
                    "needs_review": False,
                    "review_reasons": [],
                    "warnings": [],
                }
            ],
            "needs_review": False,
            "review_reasons": [],
            "warnings": [],
        }
    )

    resolved = resolve_relative_month_ranges(extraction, "2026-08-17")

    group = resolved.groups[0]
    assert group.relative_month_count == 6
    assert (group.start_month, group.end_month) == ("2026-02", "2026-07")
    assert group.needs_review
    assert resolved.needs_review
    assert "原文“近半年”表示6个月，模型返回10个月" in (
        group.review_reasons[0]
    )


def test_explicit_range_keeps_an_end_month_equal_to_application_month() -> None:
    extraction = validate_extraction_payload(
        {
            "requirements": [
                {
                    "sequence": 1,
                    "source_text": "需要霍宝秀社保 2025年1月到2026年7月",
                    "type": "rights_statement",
                    "supported": True,
                    "reason": "",
                }
            ],
            "groups": [
                {
                    "requirement_sequence": 1,
                    "print_mode": None,
                    "insurance_type": "养老",
                    "start_month": "2025-01",
                    "end_month": "2026-07",
                    "time_expression": "2025年1月到2026年7月",
                    "date_basis": "explicit_range",
                    "relative_month_count": None,
                    "evidence": "需要霍宝秀社保 2025年1月到2026年7月",
                    "people": [
                        {
                            "name": "霍宝秀",
                            "social_security_number": None,
                            "evidence": "需要霍宝秀社保 2025年1月到2026年7月",
                            "confidence": 1.0,
                        }
                    ],
                    "needs_review": False,
                    "review_reasons": [],
                    "warnings": [],
                }
            ],
            "needs_review": False,
            "review_reasons": [],
            "warnings": [],
        }
    )

    resolved = resolve_relative_month_ranges(extraction, "2026-07-26")

    assert resolved.groups[0].date_basis == "explicit_range"
    assert (resolved.groups[0].start_month, resolved.groups[0].end_month) == (
        "2025-01",
        "2026-07",
    )


def test_program_resolves_current_previous_year_and_until_now() -> None:
    person = ExtractedPerson(name="张三", evidence="张三", confidence=0.9)

    def group(date_basis: str, start_month: str | None = None) -> ExtractedPrintGroup:
        return ExtractedPrintGroup(
            print_mode=None,
            insurance_type="养老",
            start_month=start_month,
            end_month=None,
            time_expression=date_basis,
            date_basis=date_basis,
            relative_month_count=None,
            evidence="张三",
            people=(person,),
            needs_review=False,
            review_reasons=(),
            warnings=(),
        )

    extraction = TaskExtraction(
        groups=(
            group("current_year"),
            group("previous_year"),
            group("until_now", "2025-01"),
        ),
        needs_review=False,
        review_reasons=(),
        warnings=(),
    )

    resolved = resolve_relative_month_ranges(extraction, "2026-07-26")

    assert (resolved.groups[0].start_month, resolved.groups[0].end_month) == (
        "2026-01",
        "2026-06",
    )
    assert (resolved.groups[1].start_month, resolved.groups[1].end_month) == (
        "2025-01",
        "2025-12",
    )
    assert (resolved.groups[2].start_month, resolved.groups[2].end_month) == (
        "2025-01",
        "2026-06",
    )


def test_relative_month_group_requires_month_count() -> None:
    payload = {
        "requirements": [
            {
                "sequence": 1,
                "source_text": "张三近半年社保",
                "type": "rights_statement",
                "supported": True,
                "reason": "",
            }
        ],
        "groups": [
            {
                "requirement_sequence": 1,
                "print_mode": None,
                "insurance_type": "养老",
                "start_month": None,
                "end_month": None,
                "time_expression": "近半年",
                "date_basis": "relative_months",
                "relative_month_count": None,
                "evidence": "张三近半年社保",
                "people": [
                    {
                        "name": "张三",
                        "social_security_number": None,
                        "evidence": "张三近半年社保",
                        "confidence": 0.9,
                    }
                ],
                "needs_review": False,
                "review_reasons": [],
                "warnings": [],
            }
        ],
        "needs_review": False,
        "review_reasons": [],
        "warnings": [],
    }

    with pytest.raises(AiResponseInvalidError, match="缺少 relative_month_count"):
        validate_extraction_payload(payload)


def test_extraction_rejects_reversed_month_range() -> None:
    with pytest.raises(AiResponseInvalidError, match="开始月份晚于结束月份"):
        validate_extraction_payload(
            {
                "requirements": [
                    {
                        "sequence": 1,
                        "source_text": "张三",
                        "type": "rights_statement",
                        "supported": True,
                        "reason": "",
                    }
                ],
                "groups": [
                    {
                        "requirement_sequence": 1,
                        "print_mode": None,
                        "insurance_type": "养老",
                        "start_month": "2026-08",
                        "end_month": "2026-07",
                        "time_expression": "",
                        "date_basis": "explicit_range",
                        "relative_month_count": None,
                        "evidence": "张三",
                        "people": [
                            {
                                "name": "张三",
                                "social_security_number": None,
                                "evidence": "张三",
                                "confidence": 0.8,
                            }
                        ],
                        "needs_review": False,
                        "review_reasons": [],
                        "warnings": [],
                    }
                ],
                "needs_review": False,
                "review_reasons": [],
                "warnings": [],
            }
        )


def test_extraction_preserves_print_groups_and_repeated_people() -> None:
    result = validate_extraction_payload(
        {
            "requirements": [
                {
                    "sequence": 1,
                    "source_text": "石贤明、刘勇2人打印1张，1年社保",
                    "type": "rights_statement",
                    "supported": True,
                    "reason": "",
                },
                {
                    "sequence": 2,
                    "source_text": "刘勇、李玉生打印1张，时间202601-202608",
                    "type": "rights_statement",
                    "supported": True,
                    "reason": "",
                },
            ],
            "groups": [
                {
                    "requirement_sequence": 1,
                    "print_mode": "combined",
                    "insurance_type": "养老",
                    "start_month": "2025-08",
                    "end_month": "2026-07",
                    "time_expression": "1年社保",
                    "date_basis": "relative_months",
                    "relative_month_count": 12,
                    "evidence": "石贤明、刘勇2人打印1张，1年社保",
                    "people": [
                        {
                            "name": "石贤明",
                            "social_security_number": None,
                            "evidence": "石贤明、刘勇2人打印1张",
                            "confidence": 0.98,
                        },
                        {
                            "name": "刘勇",
                            "social_security_number": None,
                            "evidence": "石贤明、刘勇2人打印1张",
                            "confidence": 0.98,
                        },
                    ],
                    "needs_review": False,
                    "review_reasons": [],
                    "warnings": [],
                },
                {
                    "requirement_sequence": 2,
                    "print_mode": "combined",
                    "insurance_type": "养老",
                    "start_month": "2026-01",
                    "end_month": "2026-08",
                    "time_expression": "202601-202608",
                    "date_basis": "explicit_range",
                    "relative_month_count": None,
                    "evidence": "刘勇、李玉生打印1张，时间202601-202608",
                    "people": [
                        {
                            "name": "刘勇",
                            "social_security_number": None,
                            "evidence": "刘勇、李玉生打印1张",
                            "confidence": 0.98,
                        },
                        {
                            "name": "李玉生",
                            "social_security_number": None,
                            "evidence": "刘勇、李玉生打印1张",
                            "confidence": 0.98,
                        },
                    ],
                    "needs_review": False,
                    "review_reasons": [],
                    "warnings": [],
                },
            ],
            "needs_review": False,
            "review_reasons": [],
            "warnings": [],
        }
    )

    assert len(result.groups) == 2
    assert result.people_count == 4
    assert [person.name for person in result.groups[0].people] == [
        "石贤明",
        "刘勇",
    ]
    assert [person.name for person in result.groups[1].people] == [
        "刘勇",
        "李玉生",
    ]


def test_multi_person_group_without_mode_is_forced_to_review() -> None:
    result = validate_extraction_payload(
        {
            "requirements": [
                {
                    "sequence": 1,
                    "source_text": "张三、李四近一年社保",
                    "type": "rights_statement",
                    "supported": True,
                    "reason": "",
                }
            ],
            "groups": [
                {
                    "requirement_sequence": 1,
                    "print_mode": None,
                    "insurance_type": "养老",
                    "start_month": "2025-08",
                    "end_month": "2026-07",
                    "time_expression": "近一年",
                    "date_basis": "relative_months",
                    "relative_month_count": 12,
                    "evidence": "张三、李四近一年社保",
                    "people": [
                        {
                            "name": "张三",
                            "social_security_number": None,
                            "evidence": "张三、李四",
                            "confidence": 0.9,
                        },
                        {
                            "name": "李四",
                            "social_security_number": None,
                            "evidence": "张三、李四",
                            "confidence": 0.9,
                        },
                    ],
                    "needs_review": False,
                    "review_reasons": [],
                    "warnings": [],
                }
            ],
            "needs_review": False,
            "review_reasons": [],
            "warnings": [],
        }
    )

    assert result.needs_review
    assert result.groups[0].needs_review
    assert result.groups[0].print_mode is None
    assert result.groups[0].review_reasons == (
        "原文未说明多人合并打印还是每人单独打印",
    )


def test_query_and_model_extraction_preserves_order_and_flattens_people(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (
        ErpTaskRecord(
            id="id-2",
            code="RLSQ-002",
            initiated_date="2026-08-20",
            title="张三社保打印",
            description="近一年",
            transaction_type="社保咨询",
            status="0",
            originator="申请人",
            department="技术中心",
        ),
        ErpTaskRecord(
            id="id-1",
            code="RLSQ-001",
            initiated_date="2026-08-19",
            title="李四社保打印",
            description="近半年",
            transaction_type="社保咨询",
            status="0",
            originator="申请人",
            department="技术中心",
        ),
    )
    calls: list[str] = []

    class FakeQueryService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def query_tasks(self, *args, **kwargs) -> ErpTaskQueryResult:
            return ErpTaskQueryResult(
                transaction_type="社保咨询",
                records=records,
                total_count=2,
                pages_fetched=1,
            )

    class FakeModelClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def ensure_available(self) -> None:
            pass

        def extract(
            self, record: ErpTaskRecord, mode: ReasoningMode
        ) -> ExtractionResponse:
            calls.append(record.code)
            person_name = "张三" if record.code == "RLSQ-002" else "李四"
            return ExtractionResponse(
                extraction=TaskExtraction(
                    groups=(
                        ExtractedPrintGroup(
                            print_mode=None,
                            insurance_type="养老",
                            start_month="2025-08",
                            end_month="2026-07",
                            time_expression="近一年",
                            date_basis="relative_months",
                            relative_month_count=12,
                            evidence=f"{person_name}近一年",
                            people=(
                                ExtractedPerson(
                                    name=person_name,
                                    evidence=f"{person_name}近一年",
                                    confidence=0.9,
                                ),
                            ),
                            needs_review=False,
                            review_reasons=(),
                            warnings=(),
                        ),
                    ),
                    needs_review=False,
                    review_reasons=(),
                    warnings=(),
                ),
                metrics=ModelMetrics(
                    model="qwen3.8:27b",
                    reasoning_mode=mode.value,
                    ollama_think=mode.ollama_think,
                    done_reason="stop",
                    total_duration_ns=1,
                    prompt_eval_count=10,
                    eval_count=20,
                    thinking_characters=0,
                ),
            )

    class FakePersonLookupService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def lookup_people(self, *, identity_numbers=(), names=(), **kwargs):
            return {}, {
                name: (
                    ErpPersonRecord(
                        id=f"person-{name}",
                        employee_code=f"code-{name}",
                        name=name,
                        identity_number=(
                            "320101199001011234"
                            if name == "张三"
                            else "320101199002021235"
                        ),
                        department="技术中心",
                        company="测试公司",
                        status="0",
                        is_quit="0",
                    ),
                )
                for name in names
            }

    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpTaskQueryService",
        FakeQueryService,
    )
    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.OllamaTaskExtractionClient",
        FakeModelClient,
    )
    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpPersonLookupService",
        FakePersonLookupService,
    )
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)

    result = ErpTaskExtractionService(
        settings,
        logging.getLogger("test.ai.workflow"),
    ).run("社保咨询", reasoning_mode="off")

    assert calls == ["RLSQ-002", "RLSQ-001"]
    assert result["summary"] == {
        "tasks_total": 2,
        "tasks_succeeded": 2,
        "tasks_failed": 0,
        "tasks_needing_review": 0,
        "print_groups_extracted": 2,
        "print_groups_pending_mode": 0,
        "people_extracted": 2,
        "identities_matched": 2,
        "identities_pending": 0,
        "tasks_processed": 2,
        "tasks_unprocessed": 0,
        "stopped": False,
    }
    requests = result["rights_statement_requests"]
    assert isinstance(requests, list)
    assert [item["task_number"] for item in requests] == [
        "RLSQ-002",
        "RLSQ-001",
    ]
    assert requests[0]["social_security_number"] == "320101199001011234"
    assert requests[0]["identity_match"]["code"] == "SUCCESS"
    assert requests[0]["group_id"] == "RLSQ-002-G01"
    assert requests[0]["source_print_mode"] is None
    assert requests[0]["resolved_print_mode"] == "individual"
    assert requests[0]["relative_month_count"] == 12


def test_extraction_service_keeps_same_person_in_different_print_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ErpTaskRecord(
        id="erp-id",
        code="RLSQ-GROUPS",
        initiated_date="2026-08-20",
        title="多组社保打印",
        description="张三李四一组，张三王五另一组",
        transaction_type="社保咨询",
        status="0",
        originator="申请人",
        department="技术中心",
    )

    class FakeQueryService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def query_tasks(self, *args, **kwargs) -> ErpTaskQueryResult:
            return ErpTaskQueryResult(
                transaction_type="社保咨询",
                records=(record,),
                total_count=1,
                pages_fetched=1,
            )

    class FakeModelClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def ensure_available(self) -> None:
            pass

        def extract(self, *args, **kwargs) -> ExtractionResponse:
            def person(name: str) -> ExtractedPerson:
                return ExtractedPerson(name=name, evidence=name, confidence=0.95)

            def group(*names: str) -> ExtractedPrintGroup:
                return ExtractedPrintGroup(
                    print_mode="combined",
                    insurance_type="养老",
                    start_month="2025-08",
                    end_month="2026-07",
                    time_expression="近一年",
                    date_basis="relative_months",
                    relative_month_count=12,
                    evidence="、".join(names),
                    people=tuple(person(name) for name in names),
                    needs_review=False,
                    review_reasons=(),
                    warnings=(),
                )

            return ExtractionResponse(
                extraction=TaskExtraction(
                    groups=(group("张三", "李四"), group("张三", "王五")),
                    needs_review=False,
                    review_reasons=(),
                    warnings=(),
                ),
                metrics=ModelMetrics(
                    model="qwen3.5:9b",
                    reasoning_mode="off",
                    ollama_think=False,
                    done_reason="stop",
                    total_duration_ns=1,
                    prompt_eval_count=1,
                    eval_count=1,
                    thinking_characters=0,
                ),
            )

    queried_names: list[str] = []

    class FakePersonLookupService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def lookup_people(self, *, identity_numbers=(), names=(), **kwargs):
            queried_names.extend(names)
            identities = {
                "张三": "320101199001011234",
                "李四": "320101199002021235",
                "王五": "320101199003031236",
            }
            return {}, {
                name: (
                    ErpPersonRecord(
                        id=f"person-{name}",
                        employee_code=f"code-{name}",
                        name=name,
                        identity_number=identities[name],
                        department="项目部",
                        company="测试单位",
                        status="0",
                        is_quit="0",
                    ),
                )
                for name in names
            }

    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpTaskQueryService",
        FakeQueryService,
    )
    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.OllamaTaskExtractionClient",
        FakeModelClient,
    )
    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpPersonLookupService",
        FakePersonLookupService,
    )
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)

    result = ErpTaskExtractionService(
        settings,
        logging.getLogger("test.ai.print-groups"),
    ).run("社保咨询", reasoning_mode="off")

    requests = result["rights_statement_requests"]
    assert queried_names == ["张三", "李四", "王五"]
    assert [item["name"] for item in requests] == ["张三", "李四", "张三", "王五"]
    assert [item["group_id"] for item in requests] == [
        "RLSQ-GROUPS-G01",
        "RLSQ-GROUPS-G01",
        "RLSQ-GROUPS-G02",
        "RLSQ-GROUPS-G02",
    ]
    assert requests[0]["social_security_number"] == requests[2][
        "social_security_number"
    ]
    assert result["summary"]["print_groups_extracted"] == 2
    assert result["summary"]["people_extracted"] == 4


def test_stop_after_active_model_request_preserves_completed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = tuple(
        ErpTaskRecord(
            id=f"id-{index}",
            code=f"RLSQ-{index:03d}",
            initiated_date="2026-08-20",
            title=f"人员{index}社保打印",
            description="近一年",
            transaction_type="社保咨询",
            status="0",
            originator="申请人",
            department="技术中心",
        )
        for index in range(1, 4)
    )
    cancelled = False

    class FakeQueryService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def query_tasks(self, *args, **kwargs) -> ErpTaskQueryResult:
            return ErpTaskQueryResult("社保咨询", records, 3, 1)

    class FakeModelClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def ensure_available(self) -> None:
            pass

        def extract(
            self, record: ErpTaskRecord, mode: ReasoningMode
        ) -> ExtractionResponse:
            nonlocal cancelled
            cancelled = True
            return ExtractionResponse(
                extraction=TaskExtraction(
                    groups=(
                        ExtractedPrintGroup(
                            print_mode=None,
                            insurance_type="养老",
                            start_month="2025-08",
                            end_month="2026-07",
                            time_expression="近一年",
                            date_basis="relative_months",
                            relative_month_count=12,
                            evidence="张三近一年",
                            people=(
                                ExtractedPerson(
                                    name="张三",
                                    evidence="张三近一年",
                                    confidence=0.9,
                                ),
                            ),
                            needs_review=False,
                            review_reasons=(),
                            warnings=(),
                        ),
                    ),
                    needs_review=False,
                    review_reasons=(),
                    warnings=(),
                ),
                metrics=ModelMetrics(
                    model="qwen3.8:27b",
                    reasoning_mode=mode.value,
                    ollama_think=mode.ollama_think,
                    done_reason="stop",
                    total_duration_ns=1,
                    prompt_eval_count=1,
                    eval_count=1,
                    thinking_characters=0,
                ),
            )

    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpTaskQueryService",
        FakeQueryService,
    )
    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.OllamaTaskExtractionClient",
        FakeModelClient,
    )
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)

    result = ErpTaskExtractionService(
        settings,
        logging.getLogger("test.ai.stop"),
        cancel_check=lambda: cancelled,
    ).run("社保咨询")

    assert result["summary"]["stopped"] is True
    assert result["summary"]["tasks_processed"] == 1
    assert result["summary"]["tasks_unprocessed"] == 2
    assert len(result["tasks"]) == 1
    assert len(result["rights_statement_requests"]) == 1


def test_identity_enrichment_does_not_guess_when_name_is_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePersonLookupService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def lookup_people(self, *, identity_numbers=(), names=(), **kwargs):
            return {}, {
                "张三": (
                    ErpPersonRecord(
                        "id-1", "001", "张三", "320101199001011234",
                        "一部", "测试公司", "0", "0",
                    ),
                    ErpPersonRecord(
                        "id-2", "002", "张三", "320101199002021235",
                        "二部", "测试公司", "0", "0",
                    ),
                ),
                "李四": (),
            }

    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpPersonLookupService",
        FakePersonLookupService,
    )
    service = ErpTaskExtractionService(
        load_settings(Path("config/settings.toml"), data_root=tmp_path),
        logging.getLogger("test.ai.identity"),
    )
    requests: list[dict[str, object]] = [
        {"name": "张三", "social_security_number": None},
        {"name": "李四", "social_security_number": None},
    ]

    stopped = service._enrich_identities(requests, credentials=None)

    assert stopped is False
    assert requests[0]["social_security_number"] is None
    assert requests[0]["identity_match"]["code"] == "ERP_PERSON_AMBIGUOUS"
    assert len(requests[0]["identity_match"]["candidates"]) == 2
    assert requests[1]["identity_match"]["code"] == "ERP_PERSON_NOT_FOUND"


def test_identity_enrichment_uses_birth_year_hint_for_same_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePersonLookupService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def lookup_people(self, *, identity_numbers=(), names=(), **kwargs):
            assert list(names) == ["陈文"]
            return {}, {
                "陈文": (
                    ErpPersonRecord(
                        "id-1984", "001", "陈文", "340403198406121626",
                        "合同管理部", "测试公司", "0", "0",
                    ),
                    ErpPersonRecord(
                        "id-1987", "002", "陈文", "340322198712011234",
                        "华南经营分公司", "测试公司", "0", "0",
                    ),
                ),
            }

    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpPersonLookupService",
        FakePersonLookupService,
    )
    service = ErpTaskExtractionService(
        load_settings(Path("config/settings.toml"), data_root=tmp_path),
        logging.getLogger("test.ai.identity.birth_year"),
    )
    requests: list[dict[str, object]] = [
        {
            "name": "陈文",
            "social_security_number": None,
            "birth_year_hint": 1987,
        }
    ]

    stopped = service._enrich_identities(requests, credentials=None)

    assert stopped is False
    assert requests[0]["social_security_number"] == "340322198712011234"
    assert requests[0]["identity_match"] == {
        "code": "SUCCESS",
        "message": "处理成功",
        "details": "已使用姓名和出生年份匹配 ERP 人员信息",
        "source": "erp_person_database_birth_year",
        "employee_code": "002",
        "department": "华南经营分公司",
        "company": "测试公司",
    }


def test_birth_year_hint_is_read_from_application_text(tmp_path: Path) -> None:
    service = ErpTaskExtractionService(
        load_settings(Path("config/settings.toml"), data_root=tmp_path),
        logging.getLogger("test.ai.birth_year.source"),
    )
    record = ErpTaskRecord(
        id="erp-id",
        code="RLSQ-BIRTH-YEAR",
        initiated_date="2026-06-29",
        title="人员近一年社保清单",
        description="打印张辉（1985）、陈文(1987)近一年社保清单",
        transaction_type="社保咨询",
        status="50",
        originator="申请人",
        department="第十六分公司",
    )

    assert service._birth_year_hint_from_application_text(record, "张辉") == 1985
    assert service._birth_year_hint_from_application_text(record, "陈文") == 1987
    assert service._birth_year_hint_from_application_text(record, "刘洋") is None


def test_identity_from_application_text_queries_person_by_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IdentityPersonLookupService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def lookup_people(self, *, identity_numbers=(), names=(), **kwargs):
            assert list(identity_numbers) == ["320681199910100032"]
            assert list(names) == []
            return {
                "320681199910100032": (
                    ErpPersonRecord(
                        "person-id",
                        "2026001",
                        "施瀛博",
                        "320681199910100032",
                        "项目管理部",
                        "南京南化建设有限公司",
                        "0",
                        "0",
                    ),
                )
            }, {}

    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpPersonLookupService",
        IdentityPersonLookupService,
    )
    service = ErpTaskExtractionService(
        load_settings(Path("config/settings.toml"), data_root=tmp_path),
        logging.getLogger("test.ai.source_identity"),
    )
    record = ErpTaskRecord(
        id="erp-id",
        code="RLSQ20260818-0006",
        initiated_date="2026-08-18",
        title="查询施瀛博8月医保权益单",
        description="请查询施瀛博（320681199910100032）8月医保权益单",
        transaction_type="社保咨询",
        status="20",
        originator="申请人",
        department="项目管理公司",
    )

    identity = service._identity_from_application_text(
        record,
        "施瀛博",
        "320681199910100032",
    )
    requests: list[dict[str, object]] = [
        {"name": "施瀛博", "social_security_number": identity}
    ]

    stopped = service._enrich_identities(requests, credentials=None)

    assert stopped is False
    assert requests[0]["social_security_number"] == "320681199910100032"
    assert requests[0]["identity_match"] == {
        "code": "SUCCESS",
        "message": "处理成功",
        "details": "已使用申请原文身份证精确匹配 ERP 人员信息",
        "source": "application_identity",
        "employee_code": "2026001",
        "department": "项目管理部",
        "company": "南京南化建设有限公司",
    }


def test_identity_lookup_keeps_source_id_and_empty_org_when_person_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyIdentityLookupService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def lookup_people(self, *, identity_numbers=(), names=(), **kwargs):
            assert list(identity_numbers) == ["320681199910100032"]
            assert list(names) == []
            return {"320681199910100032": ()}, {}

    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpPersonLookupService",
        EmptyIdentityLookupService,
    )
    service = ErpTaskExtractionService(
        load_settings(Path("config/settings.toml"), data_root=tmp_path),
        logging.getLogger("test.ai.source_identity.not_found"),
    )
    requests: list[dict[str, object]] = [
        {
            "name": "施瀛博",
            "social_security_number": "320681199910100032",
        }
    ]

    stopped = service._enrich_identities(requests, credentials=None)

    assert stopped is False
    assert requests[0]["social_security_number"] == "320681199910100032"
    assert requests[0]["identity_match"]["code"] == "ERP_PERSON_NOT_FOUND"
    assert requests[0]["identity_match"]["department"] == ""
    assert requests[0]["identity_match"]["company"] == ""


def test_identity_from_application_text_recovers_id_when_model_omits_it(
    tmp_path: Path,
) -> None:
    service = ErpTaskExtractionService(
        load_settings(Path("config/settings.toml"), data_root=tmp_path),
        logging.getLogger("test.ai.source_identity.fallback"),
    )
    record = ErpTaskRecord(
        id="erp-id",
        code="RLSQ20260818-0006",
        initiated_date="2026-08-18",
        title="查询施瀛博8月医保权益单",
        description="请查询施瀛博（320681199910100032）8月医保权益单",
        transaction_type="社保咨询",
        status="20",
        originator="申请人",
        department="项目管理公司",
    )

    assert service._identity_from_application_text(record, "施瀛博", None) == (
        "320681199910100032"
    )


def test_identity_from_application_text_rejects_another_persons_id(
    tmp_path: Path,
) -> None:
    service = ErpTaskExtractionService(
        load_settings(Path("config/settings.toml"), data_root=tmp_path),
        logging.getLogger("test.ai.source_identity.wrong_person"),
    )
    record = ErpTaskRecord(
        id="erp-id",
        code="RLSQ20260818-0004",
        initiated_date="2026-08-18",
        title="项目投标需人员社保",
        description="陈文 340322198712011234\n蔡进\n人员社保打印",
        transaction_type="社保咨询",
        status="50",
        originator="申请人",
        department="项目管理公司",
    )

    assert service._identity_from_application_text(
        record,
        "蔡进",
        "340322198712011234",
    ) is None


def test_identity_lookup_rejects_person_name_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MismatchedIdentityLookupService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def lookup_people(self, *, identity_numbers=(), names=(), **kwargs):
            return {
                "340322198712011234": (
                    ErpPersonRecord(
                        "person-id",
                        "employee-code",
                        "陈文",
                        "340322198712011234",
                        "华南经营分公司",
                        "南京南化建设有限公司",
                        "0",
                        "0",
                    ),
                )
            }, {}

    monkeypatch.setattr(
        "ehrm.modules.erp.extraction_service.ErpPersonLookupService",
        MismatchedIdentityLookupService,
    )
    service = ErpTaskExtractionService(
        load_settings(Path("config/settings.toml"), data_root=tmp_path),
        logging.getLogger("test.ai.identity_name_mismatch"),
    )
    requests: list[dict[str, object]] = [
        {
            "name": "蔡进",
            "social_security_number": "340322198712011234",
        }
    ]

    service._enrich_identities(requests, credentials=None)

    assert requests[0]["social_security_number"] is None
    assert requests[0]["identity_match"]["code"] == (
        "ERP_PERSON_IDENTITY_NAME_MISMATCH"
    )
    assert requests[0]["identity_match"]["department"] == ""
    assert requests[0]["identity_match"]["company"] == ""


def test_person_lookup_progress_counts_identity_and_name_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress: list[str] = []

    class FakeSession:
        page = object()
        request = object()

        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def ensure_authenticated(self, credentials) -> None:
            pass

    class FakePersonClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def query_by_identity_number(self, identity):
            return ()

        def query_by_name(self, name):
            return ()

    monkeypatch.setattr(
        "ehrm.modules.erp.person_service.ErpSession",
        FakeSession,
    )
    monkeypatch.setattr(
        "ehrm.modules.erp.person_service.ErpPersonClient",
        FakePersonClient,
    )
    service = ErpPersonLookupService(
        load_settings(Path("config/settings.toml"), data_root=tmp_path),
        logging.getLogger("test.erp.person.progress"),
        progress_callback=progress.append,
    )

    service.lookup_people(
        identity_numbers=["340322198712011234"],
        names=[f"人员{index}" for index in range(1, 10)],
        credentials=ErpCredentials("user", "password"),
    )

    assert "1/10" in progress[0]
    assert "10/10" in progress[-1]
