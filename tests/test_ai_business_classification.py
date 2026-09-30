from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ehrm.core.exceptions import AiResponseInvalidError
from ehrm.core.settings import load_settings
from ehrm.modules.ai.business_classification import (
    validate_business_classification_payload,
)
from ehrm.modules.ai.client import OllamaTaskExtractionClient
from ehrm.modules.ai.models import ReasoningMode
from ehrm.modules.erp.models import ErpTaskRecord


def _record(
    title: str,
    description: str = "",
    *,
    transaction_type: str = "社保咨询",
) -> ErpTaskRecord:
    return ErpTaskRecord(
        id="erp-1",
        code="RLSQ-001",
        initiated_date="2026-09-28",
        title=title,
        description=description,
        transaction_type=transaction_type,
        status="50",
        originator="申请人",
        department="部门",
    )


@pytest.mark.parametrize(
    ("record", "model_type", "evidence", "expected"),
    [
        (
            _record("关于苏兆瑞停缴社保的申请"),
            "employment_termination",
            "停缴社保",
            "退工停保登记",
        ),
        (
            _record("合作单位人员赵佳男停缴社保事宜"),
            "employment_termination",
            "停缴社保",
            "退工停保登记",
        ),
        (
            _record("5位新员工合同后续事宜", "另需从8月开始缴纳永利重工社保"),
            "employment_enrollment",
            "开始缴纳永利重工社保",
            "用工参保登记",
        ),
        (
            _record("请打印常伟、丁佐宏的社保证明"),
            "rights_statement",
            "打印常伟、丁佐宏的社保证明",
            "单位社保权益单",
        ),
    ],
)
def test_known_business_type_uses_model_intent_and_source_evidence(
    record: ErpTaskRecord,
    model_type: str,
    evidence: str,
    expected: str,
) -> None:
    result = validate_business_classification_payload(
        {"type": model_type, "evidence": evidence, "reason": ""},
        record,
    )

    assert result.business_type == expected
    assert result.classified is True
    assert result.evidence == evidence


def test_unknown_intent_retains_original_erp_transaction_type() -> None:
    record = _record("请协助处理以下事项", "请联系相关部门确认", transaction_type="社保咨询")

    result = validate_business_classification_payload(
        {"type": "unknown", "evidence": "", "reason": "未明确要求办理哪种社保业务"},
        record,
    )

    assert result.business_type == "社保咨询"
    assert result.classified is False
    assert result.reason == "未明确要求办理哪种社保业务"


@pytest.mark.parametrize(
    "evidence",
    [
        "因个人原因离职需要从 2026 年 10 月开始停交社保",
        "因个人离职需要从2026年10月开始停交社保",
        "申请要求从十月份停止为员工缴纳社保",
        "",
    ],
    ids=["spacing", "omitted-word", "paraphrase", "empty-explanation"],
)
def test_classification_evidence_is_explanatory_not_a_verbatim_gate(
    evidence: str,
) -> None:
    result = validate_business_classification_payload(
        {"type": "employment_termination", "evidence": evidence, "reason": ""},
        _record(
            "关于苏兆瑞停缴社保的申请",
            "因个人原因离职需要从2026年10月开始停交社保",
        ),
    )

    assert result.business_type == "退工停保登记"
    assert result.classified is True
    assert result.evidence == evidence


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "employment_termination", "reason": ""},
        {"type": "employment_termination", "evidence": "停缴", "reason": "", "extra": True},
        {"type": "employment_termination", "evidence": ["停缴"], "reason": ""},
        {"type": "employment_termination", "evidence": "停缴", "reason": None},
    ],
    ids=["missing-field", "unexpected-field", "non-text-evidence", "non-text-reason"],
)
def test_classification_still_rejects_invalid_structure_and_field_types(
    payload: object,
) -> None:
    with pytest.raises(AiResponseInvalidError):
        validate_business_classification_payload(payload, _record("请停缴社保"))


def test_classification_rejects_unsupported_mixed_type() -> None:
    with pytest.raises(AiResponseInvalidError, match="type"):
        validate_business_classification_payload(
            {"type": "mixed", "evidence": "参保", "reason": ""},
            _record("请参保"),
        )


def test_classifier_sends_full_erp_context_and_parses_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    client = OllamaTaskExtractionClient(settings.ai, logging.getLogger("test.ai.classify"))
    record = _record(
        "5位新员工合同后续事宜",
        "另需从8月开始缴纳永利重工社保",
    )
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, *, payload: dict, operation: str) -> dict:
        captured.update({"method": method, "url": url, "payload": payload})
        return {
            "model": settings.ai.model,
            "message": {
                "content": json.dumps(
                    {
                        "type": "employment_enrollment",
                        "evidence": "开始缴纳永利重工社保",
                        "reason": "",
                    },
                    ensure_ascii=False,
                )
            },
            "done_reason": "stop",
        }

    monkeypatch.setattr(client, "_request_json", fake_request)
    result = client.classify(record, ReasoningMode.OFF)

    assert result.business_type == "用工参保登记"
    assert captured["method"] == "POST"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["format"]["properties"]["type"]["enum"] == [
        "rights_statement",
        "employment_termination",
        "employment_enrollment",
        "unknown",
    ]
    assert json.loads(payload["messages"][1]["content"]) == {
        "transaction_type": "社保咨询",
        "application_date": "2026-09-28",
        "title_summary": "5位新员工合同后续事宜",
        "request_details": "另需从8月开始缴纳永利重工社保",
    }
