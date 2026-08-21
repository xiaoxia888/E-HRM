from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import re
from typing import Any

from ehrm.core.exceptions import AiResponseInvalidError


_MONTH_PATTERN = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])")
_IDENTITY_PATTERN = re.compile(r"(?:\d{15}|\d{17}[0-9X])")


class AiModelProfile(StrEnum):
    """Stable model identifiers used by configuration and preferences."""

    QWEN3_5_9B = "qwen3_5_9b"
    QWEN3_8_27B = "qwen3_8_27b"


class ReasoningMode(StrEnum):
    """Provider-independent reasoning modes exposed to the desktop UI."""

    OFF = "off"
    ON = "on"
    LOW = "low"
    MEDIUM = "medium"
    MAX = "max"

    @property
    def label(self) -> str:
        return {
            ReasoningMode.OFF: "非思考",
            ReasoningMode.ON: "思考",
            ReasoningMode.LOW: "低强度",
            ReasoningMode.MEDIUM: "中等强度",
            ReasoningMode.MAX: "最高强度",
        }[self]

    @property
    def ollama_think(self) -> bool | str:
        return {
            ReasoningMode.OFF: False,
            ReasoningMode.ON: True,
            ReasoningMode.LOW: "low",
            ReasoningMode.MEDIUM: "medium",
            ReasoningMode.MAX: "max",
        }[self]

    @classmethod
    def parse(cls, value: str | "ReasoningMode") -> "ReasoningMode":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise AiResponseInvalidError(
                "推理模式无效，只能是 off、on、low、medium 或 max"
            ) from exc


class DateBasis(StrEnum):
    EXPLICIT_RANGE = "explicit_range"
    RELATIVE_MONTHS = "relative_months"
    CURRENT_YEAR = "current_year"
    PREVIOUS_YEAR = "previous_year"
    UNTIL_NOW = "until_now"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ExtractedPerson:
    name: str
    start_month: str | None
    end_month: str | None
    time_expression: str
    evidence: str
    date_basis: str
    confidence: float
    social_security_number: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskExtraction:
    people: tuple[ExtractedPerson, ...]
    needs_review: bool
    review_reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "people": [person.as_dict() for person in self.people],
            "needs_review": self.needs_review,
            "review_reasons": list(self.review_reasons),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class ModelMetrics:
    model: str
    reasoning_mode: str
    ollama_think: bool | str
    done_reason: str
    total_duration_ns: int
    prompt_eval_count: int
    eval_count: int
    thinking_characters: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExtractionResponse:
    extraction: TaskExtraction
    metrics: ModelMetrics


EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["people", "needs_review", "review_reasons", "warnings"],
    "properties": {
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "name",
                    "social_security_number",
                    "start_month",
                    "end_month",
                    "time_expression",
                    "evidence",
                    "date_basis",
                    "confidence",
                ],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "social_security_number": {
                        "type": ["string", "null"],
                        "pattern": "^(?:[0-9]{15}|[0-9]{17}[0-9Xx])$",
                    },
                    "start_month": {
                        "type": ["string", "null"],
                        "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$",
                    },
                    "end_month": {
                        "type": ["string", "null"],
                        "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$",
                    },
                    "time_expression": {"type": "string"},
                    "evidence": {"type": "string"},
                    "date_basis": {
                        "type": "string",
                        "enum": [item.value for item in DateBasis],
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
            },
        },
        "needs_review": {"type": "boolean"},
        "review_reasons": {
            "type": "array",
            "items": {"type": "string"},
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


def validate_extraction_payload(payload: object) -> TaskExtraction:
    """Performs strict runtime validation independent of model guarantees."""

    if not isinstance(payload, dict):
        raise AiResponseInvalidError("模型结果根节点必须是 JSON 对象")
    required = {"people", "needs_review", "review_reasons", "warnings"}
    if set(payload) != required:
        raise AiResponseInvalidError(
            "模型结果字段不完整或包含未知字段",
            details=f"实际字段：{sorted(str(key) for key in payload)}",
        )
    if not isinstance(payload["people"], list):
        raise AiResponseInvalidError("模型结果 people 必须是数组")
    if not isinstance(payload["needs_review"], bool):
        raise AiResponseInvalidError("模型结果 needs_review 必须是布尔值")

    review_reasons = _string_tuple(payload["review_reasons"], "review_reasons")
    warnings = _string_tuple(payload["warnings"], "warnings")
    people: list[ExtractedPerson] = []
    expected_person_fields = {
        "name",
        "social_security_number",
        "start_month",
        "end_month",
        "time_expression",
        "evidence",
        "date_basis",
        "confidence",
    }
    for index, raw_person in enumerate(payload["people"], start=1):
        if not isinstance(raw_person, dict) or set(raw_person) != expected_person_fields:
            raise AiResponseInvalidError(f"第 {index} 个人员结果字段不正确")
        name = _required_text(raw_person["name"], f"people[{index}].name")
        social_security_number = _identity(
            raw_person["social_security_number"],
            f"people[{index}].social_security_number",
        )
        start_month = _month(raw_person["start_month"], f"people[{index}].start_month")
        end_month = _month(raw_person["end_month"], f"people[{index}].end_month")
        if start_month and end_month and start_month > end_month:
            raise AiResponseInvalidError(
                f"第 {index} 个人员的开始月份晚于结束月份"
            )
        date_basis_value = _required_text(
            raw_person["date_basis"], f"people[{index}].date_basis"
        )
        try:
            date_basis = DateBasis(date_basis_value).value
        except ValueError as exc:
            raise AiResponseInvalidError(
                f"第 {index} 个人员的 date_basis 无效"
            ) from exc
        confidence = raw_person["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            raise AiResponseInvalidError(
                f"第 {index} 个人员的 confidence 必须在 0 至 1 之间"
            )
        people.append(
            ExtractedPerson(
                name=name,
                start_month=start_month,
                end_month=end_month,
                time_expression=_text(
                    raw_person["time_expression"],
                    f"people[{index}].time_expression",
                ),
                evidence=_text(
                    raw_person["evidence"], f"people[{index}].evidence"
                ),
                date_basis=date_basis,
                confidence=float(confidence),
                social_security_number=social_security_number,
            )
        )

    needs_review = payload["needs_review"]
    if not people and not needs_review:
        raise AiResponseInvalidError("未识别到人员时 needs_review 必须为 true")
    if needs_review and not review_reasons:
        raise AiResponseInvalidError("需要人工复核时必须给出 review_reasons")
    return TaskExtraction(
        people=tuple(people),
        needs_review=needs_review,
        review_reasons=review_reasons,
        warnings=warnings,
    )


def _month(value: object, field: str) -> str | None:
    if value is None:
        return None
    text = _required_text(value, field)
    if not _MONTH_PATTERN.fullmatch(text):
        raise AiResponseInvalidError(f"模型结果 {field} 不是 YYYY-MM")
    return text


def _identity(value: object, field: str) -> str | None:
    if value is None:
        return None
    text = _required_text(value, field).upper()
    if not _IDENTITY_PATTERN.fullmatch(text):
        raise AiResponseInvalidError(
            f"模型结果 {field} 不是合法的 15 位或 18 位身份证格式"
        )
    return text


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise AiResponseInvalidError(f"模型结果 {field} 必须是字符串")
    return value.strip()


def _required_text(value: object, field: str) -> str:
    text = _text(value, field)
    if not text:
        raise AiResponseInvalidError(f"模型结果 {field} 不能为空")
    return text


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AiResponseInvalidError(f"模型结果 {field} 必须是字符串数组")
    return tuple(item.strip() for item in value if item.strip())
