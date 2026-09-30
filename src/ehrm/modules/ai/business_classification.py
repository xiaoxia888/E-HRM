from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ehrm.core.exceptions import AiResponseInvalidError
from ehrm.modules.erp.models import ErpTaskRecord


class BusinessIntent(StrEnum):
    RIGHTS_STATEMENT = "rights_statement"
    EMPLOYMENT_TERMINATION = "employment_termination"
    EMPLOYMENT_ENROLLMENT = "employment_enrollment"
    UNKNOWN = "unknown"


_BUSINESS_TYPE_NAMES = {
    BusinessIntent.RIGHTS_STATEMENT: "单位社保权益单",
    BusinessIntent.EMPLOYMENT_TERMINATION: "退工停保登记",
    BusinessIntent.EMPLOYMENT_ENROLLMENT: "用工参保登记",
}


BUSINESS_CLASSIFICATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "evidence", "reason"],
    "properties": {
        "type": {
            "type": "string",
            "enum": [intent.value for intent in BusinessIntent],
        },
        "evidence": {"type": "string"},
        "reason": {"type": "string"},
    },
}


@dataclass(frozen=True, slots=True)
class BusinessClassification:
    business_type: str
    source_transaction_type: str
    classified: bool
    evidence: str
    reason: str


def validate_business_classification_payload(
    payload: object,
    record: ErpTaskRecord,
) -> BusinessClassification:
    """Validates the decision contract, not the wording of its explanation."""
    if not isinstance(payload, dict) or set(payload) != {"type", "evidence", "reason"}:
        raise AiResponseInvalidError("业务分类结果字段不正确")
    try:
        intent = BusinessIntent(payload["type"])
    except (TypeError, ValueError) as exc:
        raise AiResponseInvalidError("业务分类 type 无效") from exc
    if not isinstance(payload["evidence"], str) or not isinstance(
        payload["reason"], str
    ):
        raise AiResponseInvalidError("业务分类依据和原因必须是文本")
    evidence = payload["evidence"].strip()
    reason = payload["reason"].strip()
    if intent is BusinessIntent.UNKNOWN:
        if not reason:
            raise AiResponseInvalidError("无法判断业务类型时必须说明原因")
        return BusinessClassification(
            business_type=record.transaction_type,
            source_transaction_type=record.transaction_type,
            classified=False,
            evidence=evidence,
            reason=reason,
        )
    # 分类依据仅供人工查看；不以摘抄准确度决定分类是否成功。
    # 姓名与身份证的来源核验由独立的人员解析校验器负责。
    if reason:
        raise AiResponseInvalidError("已确定业务类型时原因必须为空")
    return BusinessClassification(
        business_type=_BUSINESS_TYPE_NAMES[intent],
        source_transaction_type=record.transaction_type,
        classified=True,
        evidence=evidence,
        reason="",
    )
