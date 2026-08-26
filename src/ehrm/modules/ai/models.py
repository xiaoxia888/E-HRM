from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
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


class PrintMode(StrEnum):
    COMBINED = "combined"
    INDIVIDUAL = "individual"


class RequirementType(StrEnum):
    """Semantic categories produced before print-group extraction."""

    RIGHTS_STATEMENT = "rights_statement"
    STATISTICS = "statistics"
    COORDINATION = "coordination"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ExtractedRequirement:
    sequence: int
    source_text: str
    requirement_type: str
    supported: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "source_text": self.source_text,
            "type": self.requirement_type,
            "supported": self.supported,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ExtractedPerson:
    name: str
    evidence: str
    confidence: float
    social_security_number: str | None = None
    birth_year_hint: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExtractedPrintGroup:
    print_mode: str | None
    insurance_type: str
    start_month: str | None
    end_month: str | None
    time_expression: str
    date_basis: str
    relative_month_count: int | None
    evidence: str
    people: tuple[ExtractedPerson, ...]
    needs_review: bool
    review_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    requirement_sequence: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_sequence": self.requirement_sequence,
            "print_mode": self.print_mode,
            "insurance_type": self.insurance_type,
            "start_month": self.start_month,
            "end_month": self.end_month,
            "time_expression": self.time_expression,
            "date_basis": self.date_basis,
            "relative_month_count": self.relative_month_count,
            "evidence": self.evidence,
            "people": [person.as_dict() for person in self.people],
            "needs_review": self.needs_review,
            "review_reasons": list(self.review_reasons),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class TaskExtraction:
    groups: tuple[ExtractedPrintGroup, ...]
    needs_review: bool
    review_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    requirements: tuple[ExtractedRequirement, ...] = ()

    @property
    def people_count(self) -> int:
        return sum(len(group.people) for group in self.groups)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirements": [item.as_dict() for item in self.requirements],
            "groups": [group.as_dict() for group in self.groups],
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
    "required": [
        "requirements",
        "groups",
        "needs_review",
        "review_reasons",
        "warnings",
    ],
    "properties": {
        "requirements": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "sequence",
                    "source_text",
                    "type",
                    "supported",
                    "reason",
                ],
                "properties": {
                    "sequence": {"type": "integer", "minimum": 1},
                    "source_text": {"type": "string", "minLength": 1},
                    "type": {
                        "type": "string",
                        "enum": [item.value for item in RequirementType],
                    },
                    "supported": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
        },
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "requirement_sequence",
                    "print_mode",
                    "insurance_type",
                    "start_month",
                    "end_month",
                    "time_expression",
                    "date_basis",
                    "relative_month_count",
                    "evidence",
                    "people",
                    "needs_review",
                    "review_reasons",
                    "warnings",
                ],
                "properties": {
                    "requirement_sequence": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "print_mode": {
                        "type": ["string", "null"],
                        "enum": [
                            PrintMode.COMBINED.value,
                            PrintMode.INDIVIDUAL.value,
                            None,
                        ],
                    },
                    "insurance_type": {
                        "type": "string",
                        "enum": ["养老", "工伤", "失业"],
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
                    "relative_month_count": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                    },
                    "people": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "name",
                                "social_security_number",
                                "birth_year_hint",
                                "evidence",
                                "confidence",
                            ],
                            "properties": {
                                "name": {"type": "string", "minLength": 1},
                                "social_security_number": {
                                    "type": ["string", "null"],
                                    "pattern": "^(?:[0-9]{15}|[0-9]{17}[0-9Xx])$",
                                },
                                "birth_year_hint": {
                                    "type": ["integer", "null"],
                                    "minimum": 1900,
                                    "maximum": 2099,
                                },
                                "evidence": {"type": "string"},
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
    required = {
        "requirements",
        "groups",
        "needs_review",
        "review_reasons",
        "warnings",
    }
    if set(payload) != required:
        raise AiResponseInvalidError(
            "模型结果字段不完整或包含未知字段",
            details=f"实际字段：{sorted(str(key) for key in payload)}",
        )
    if not isinstance(payload["groups"], list):
        raise AiResponseInvalidError("模型结果 groups 必须是数组")
    if not isinstance(payload["requirements"], list) or not payload["requirements"]:
        raise AiResponseInvalidError("模型结果 requirements 必须是非空数组")
    if not isinstance(payload["needs_review"], bool):
        raise AiResponseInvalidError("模型结果 needs_review 必须是布尔值")

    review_reasons = _string_tuple(payload["review_reasons"], "review_reasons")
    warnings = _string_tuple(payload["warnings"], "warnings")
    requirements: list[ExtractedRequirement] = []
    expected_requirement_fields = {
        "sequence",
        "source_text",
        "type",
        "supported",
        "reason",
    }
    for requirement_index, raw_requirement in enumerate(
        payload["requirements"],
        start=1,
    ):
        if (
            not isinstance(raw_requirement, dict)
            or set(raw_requirement) != expected_requirement_fields
        ):
            raise AiResponseInvalidError(
                f"第 {requirement_index} 个需求分类字段不正确"
            )
        sequence = raw_requirement["sequence"]
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence != requirement_index
        ):
            raise AiResponseInvalidError(
                "需求 sequence 必须从 1 开始并按原文顺序连续编号"
            )
        requirement_type_value = _required_text(
            raw_requirement["type"],
            f"requirements[{requirement_index}].type",
        )
        try:
            requirement_type = RequirementType(requirement_type_value).value
        except ValueError as exc:
            raise AiResponseInvalidError(
                f"第 {requirement_index} 个需求的 type 无效"
            ) from exc
        supported = raw_requirement["supported"]
        if not isinstance(supported, bool):
            raise AiResponseInvalidError(
                f"第 {requirement_index} 个需求的 supported 必须是布尔值"
            )
        should_be_supported = (
            requirement_type == RequirementType.RIGHTS_STATEMENT.value
        )
        if supported != should_be_supported:
            raise AiResponseInvalidError(
                f"第 {requirement_index} 个需求的 type 与 supported 相互矛盾"
            )
        reason = _text(
            raw_requirement["reason"],
            f"requirements[{requirement_index}].reason",
        )
        if not supported and not reason:
            raise AiResponseInvalidError(
                f"第 {requirement_index} 个不处理的需求必须说明原因"
            )
        requirements.append(
            ExtractedRequirement(
                sequence=sequence,
                source_text=_required_text(
                    raw_requirement["source_text"],
                    f"requirements[{requirement_index}].source_text",
                ),
                requirement_type=requirement_type,
                supported=supported,
                reason=reason,
            )
        )

    groups: list[ExtractedPrintGroup] = []
    group_signatures: dict[tuple[object, ...], int] = {}
    expected_group_fields = {
        "requirement_sequence",
        "print_mode",
        "insurance_type",
        "start_month",
        "end_month",
        "time_expression",
        "date_basis",
        "relative_month_count",
        "evidence",
        "people",
        "needs_review",
        "review_reasons",
        "warnings",
    }
    for group_index, raw_group in enumerate(payload["groups"], start=1):
        if not isinstance(raw_group, dict) or set(raw_group) != expected_group_fields:
            raise AiResponseInvalidError(f"第 {group_index} 个打印组字段不正确")
        requirement_sequence = raw_group["requirement_sequence"]
        if (
            isinstance(requirement_sequence, bool)
            or not isinstance(requirement_sequence, int)
            or not 1 <= requirement_sequence <= len(requirements)
        ):
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组引用了不存在的需求"
            )
        source_requirement = requirements[requirement_sequence - 1]
        if (
            not source_requirement.supported
            or source_requirement.requirement_type
            != RequirementType.RIGHTS_STATEMENT.value
        ):
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组引用的不是人员权益单需求",
                details=(
                    f"requirement_sequence={requirement_sequence}；"
                    f"type={source_requirement.requirement_type}"
                ),
            )
        raw_print_mode = raw_group["print_mode"]
        if raw_print_mode is None:
            print_mode = None
        else:
            try:
                print_mode = PrintMode(
                    _required_text(
                        raw_print_mode,
                        f"groups[{group_index}].print_mode",
                    )
                ).value
            except ValueError as exc:
                raise AiResponseInvalidError(
                    f"第 {group_index} 个打印组的 print_mode 无效"
                ) from exc
        insurance_type = _required_text(
            raw_group["insurance_type"],
            f"groups[{group_index}].insurance_type",
        )
        if insurance_type not in {"养老", "工伤", "失业"}:
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组的险种无效"
            )
        start_month = _month(
            raw_group["start_month"],
            f"groups[{group_index}].start_month",
        )
        end_month = _month(
            raw_group["end_month"],
            f"groups[{group_index}].end_month",
        )
        date_basis_value = _required_text(
            raw_group["date_basis"],
            f"groups[{group_index}].date_basis",
        )
        try:
            date_basis = DateBasis(date_basis_value).value
        except ValueError as exc:
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组的 date_basis 无效"
            ) from exc
        raw_relative_month_count = raw_group["relative_month_count"]
        if raw_relative_month_count is None:
            relative_month_count = None
        elif (
            isinstance(raw_relative_month_count, bool)
            or not isinstance(raw_relative_month_count, int)
            or raw_relative_month_count < 1
        ):
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组的 relative_month_count "
                "必须是大于 0 的整数或 null"
            )
        else:
            relative_month_count = raw_relative_month_count
        if date_basis == DateBasis.RELATIVE_MONTHS.value:
            if relative_month_count is None:
                raise AiResponseInvalidError(
                    f"第 {group_index} 个相对月份打印组缺少 relative_month_count"
                )
        elif relative_month_count is not None:
            raise AiResponseInvalidError(
                f"第 {group_index} 个非相对月份打印组的 "
                "relative_month_count 必须为 null"
            )
        if date_basis in {
            DateBasis.CURRENT_YEAR.value,
            DateBasis.PREVIOUS_YEAR.value,
        } and (start_month is not None or end_month is not None):
            raise AiResponseInvalidError(
                f"第 {group_index} 个 {date_basis} 打印组的起止月份必须为 null"
            )
        if date_basis == DateBasis.UNTIL_NOW.value and end_month is not None:
            raise AiResponseInvalidError(
                f"第 {group_index} 个 until_now 打印组的结束月份必须为 null"
            )
        if date_basis in {
            DateBasis.MISSING.value,
            DateBasis.AMBIGUOUS.value,
        } and (start_month is not None or end_month is not None):
            raise AiResponseInvalidError(
                f"第 {group_index} 个 {date_basis} 打印组不得生成起止月份"
            )
        if (
            date_basis != DateBasis.RELATIVE_MONTHS.value
            and start_month
            and end_month
            and start_month > end_month
        ):
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组的开始月份晚于结束月份"
            )
        if not isinstance(raw_group["people"], list) or not raw_group["people"]:
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组必须至少包含一名人员"
            )
        group_people: list[ExtractedPerson] = []
        expected_person_fields = {
            "name",
            "social_security_number",
            "evidence",
            "confidence",
        }
        expected_person_fields_with_birth_year = {
            *expected_person_fields,
            "birth_year_hint",
        }
        for person_index, raw_person in enumerate(raw_group["people"], start=1):
            if (
                not isinstance(raw_person, dict)
                or frozenset(raw_person)
                not in {
                    frozenset(expected_person_fields),
                    frozenset(expected_person_fields_with_birth_year),
                }
            ):
                raise AiResponseInvalidError(
                    f"第 {group_index} 组第 {person_index} 个人员字段不正确"
                )
            raw_birth_year_hint = raw_person.get("birth_year_hint")
            if raw_birth_year_hint is None:
                birth_year_hint = None
            elif (
                isinstance(raw_birth_year_hint, bool)
                or not isinstance(raw_birth_year_hint, int)
                or not 1900 <= raw_birth_year_hint <= 2099
            ):
                raise AiResponseInvalidError(
                    f"第 {group_index} 组第 {person_index} 个人员的 "
                    "birth_year_hint 必须是 1900 至 2099 的整数或 null"
                )
            else:
                birth_year_hint = raw_birth_year_hint
            confidence = raw_person["confidence"]
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0 <= float(confidence) <= 1
            ):
                raise AiResponseInvalidError(
                    f"第 {group_index} 组第 {person_index} 个人员的 "
                    "confidence 必须在 0 至 1 之间"
                )
            group_people.append(
                ExtractedPerson(
                    name=_required_text(
                        raw_person["name"],
                        f"groups[{group_index}].people[{person_index}].name",
                    ),
                    evidence=_text(
                        raw_person["evidence"],
                        f"groups[{group_index}].people[{person_index}].evidence",
                    ),
                    confidence=float(confidence),
                    social_security_number=_identity(
                        raw_person["social_security_number"],
                        "groups"
                        f"[{group_index}].people[{person_index}]"
                        ".social_security_number",
                    ),
                    birth_year_hint=birth_year_hint,
                )
            )
            if group_people[-1].name not in source_requirement.source_text:
                raise AiResponseInvalidError(
                    f"第 {group_index} 组人员“{group_people[-1].name}”"
                    "未出现在其引用的人员权益单需求原文中"
                )
        group_review_reasons = _string_tuple(
            raw_group["review_reasons"],
            f"groups[{group_index}].review_reasons",
        )
        group_warnings = _string_tuple(
            raw_group["warnings"],
            f"groups[{group_index}].warnings",
        )
        group_needs_review = raw_group["needs_review"]
        if not isinstance(group_needs_review, bool):
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组 needs_review 必须是布尔值"
            )
        inferred_reasons = list(group_review_reasons)
        if len(group_people) > 1 and print_mode is None:
            group_needs_review = True
            reason = "原文未说明多人合并打印还是每人单独打印"
            if reason not in inferred_reasons:
                inferred_reasons.append(reason)
        if (
            (not start_month or not end_month)
            and date_basis
            not in {
                DateBasis.RELATIVE_MONTHS.value,
                DateBasis.CURRENT_YEAR.value,
                DateBasis.PREVIOUS_YEAR.value,
                DateBasis.UNTIL_NOW.value,
            }
            and not group_needs_review
        ):
            group_needs_review = True
            inferred_reasons.append("未能确定该打印组的完整起止月份")
        if (
            date_basis == DateBasis.UNTIL_NOW.value
            and not start_month
            and not group_needs_review
        ):
            group_needs_review = True
            inferred_reasons.append("原文使用“至今”，但未能确定开始月份")
        if group_needs_review and not inferred_reasons:
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组需要复核时必须给出原因"
            )
        candidate_group = ExtractedPrintGroup(
            requirement_sequence=requirement_sequence,
            print_mode=print_mode,
            insurance_type=insurance_type,
            start_month=start_month,
            end_month=end_month,
            time_expression=_text(
                raw_group["time_expression"],
                f"groups[{group_index}].time_expression",
            ),
            date_basis=date_basis,
            relative_month_count=relative_month_count,
            evidence=_text(
                raw_group["evidence"],
                f"groups[{group_index}].evidence",
            ),
            people=tuple(group_people),
            needs_review=group_needs_review,
            review_reasons=tuple(inferred_reasons),
            warnings=group_warnings,
        )
        signature = (
            candidate_group.requirement_sequence,
            candidate_group.print_mode,
            candidate_group.insurance_type,
            candidate_group.start_month,
            candidate_group.end_month,
            candidate_group.date_basis,
            candidate_group.relative_month_count,
            tuple(
                sorted(
                    (
                        person.name,
                        person.social_security_number or "",
                        person.birth_year_hint,
                    )
                    for person in candidate_group.people
                )
            ),
        )
        previous_group_index = group_signatures.get(signature)
        if previous_group_index is not None:
            raise AiResponseInvalidError(
                f"第 {group_index} 个打印组与第 {previous_group_index} 个完全重复"
            )
        group_signatures[signature] = group_index
        groups.append(candidate_group)

    needs_review = payload["needs_review"]
    if not groups and not needs_review:
        raise AiResponseInvalidError("未识别到打印组时 needs_review 必须为 true")
    if any(group.needs_review for group in groups):
        needs_review = True
    if needs_review and not review_reasons:
        group_reasons = tuple(
            reason
            for group in groups
            for reason in group.review_reasons
        )
        if not group_reasons:
            raise AiResponseInvalidError("需要人工复核时必须给出 review_reasons")
        review_reasons = tuple(dict.fromkeys(group_reasons))
    return TaskExtraction(
        requirements=tuple(requirements),
        groups=tuple(groups),
        needs_review=needs_review,
        review_reasons=review_reasons,
        warnings=warnings,
    )


def resolve_relative_month_ranges(
    extraction: TaskExtraction,
    application_date: str,
) -> TaskExtraction:
    """Resolve semantic periods with deterministic month arithmetic.

    The model identifies explicit ranges or the semantic date basis. The
    program owns relative, natural-year and until-now arithmetic before
    downstream automation receives the final month range.
    """

    application_year, application_month = _application_year_month(
        application_date
    )
    groups: list[ExtractedPrintGroup] = []
    task_review_reasons = list(extraction.review_reasons)
    task_warnings = list(extraction.warnings)

    for group in extraction.groups:
        if group.date_basis == DateBasis.CURRENT_YEAR.value:
            if application_month == 1:
                reason = "申请月份为1月，“今年以来”没有可查询的已完成月份"
                group_reasons = list(group.review_reasons)
                if reason not in group_reasons:
                    group_reasons.append(reason)
                if reason not in task_review_reasons:
                    task_review_reasons.append(reason)
                groups.append(
                    replace(
                        group,
                        start_month=None,
                        end_month=None,
                        needs_review=True,
                        review_reasons=tuple(group_reasons),
                    )
                )
            else:
                groups.append(
                    replace(
                        group,
                        start_month=f"{application_year:04d}-01",
                        end_month=_relative_month_range(
                            application_year,
                            application_month,
                            1,
                        )[1],
                    )
                )
            continue

        if group.date_basis == DateBasis.PREVIOUS_YEAR.value:
            previous_year = application_year - 1
            groups.append(
                replace(
                    group,
                    start_month=f"{previous_year:04d}-01",
                    end_month=f"{previous_year:04d}-12",
                )
            )
            continue

        if group.date_basis == DateBasis.UNTIL_NOW.value:
            end_month = _relative_month_range(
                application_year,
                application_month,
                1,
            )[1]
            group_reasons = list(group.review_reasons)
            needs_review = group.needs_review
            if group.start_month and group.start_month > end_month:
                reason = (
                    f"“至今”的开始月份 {group.start_month} 晚于可查询结束月份 "
                    f"{end_month}"
                )
                if reason not in group_reasons:
                    group_reasons.append(reason)
                if reason not in task_review_reasons:
                    task_review_reasons.append(reason)
                needs_review = True
            groups.append(
                replace(
                    group,
                    end_month=end_month,
                    needs_review=needs_review,
                    review_reasons=tuple(group_reasons),
                )
            )
            continue

        if group.date_basis != DateBasis.RELATIVE_MONTHS.value:
            groups.append(group)
            continue

        assert group.relative_month_count is not None
        model_count = group.relative_month_count
        verified_count = _relative_month_count_from_expression(
            group.time_expression
        )
        effective_count = verified_count or model_count
        review_reasons = list(group.review_reasons)
        warnings = list(group.warnings)
        needs_review = group.needs_review

        if verified_count is not None and verified_count != model_count:
            reason = (
                f"相对时间月数冲突：原文“{group.time_expression}”表示"
                f"{verified_count}个月，模型返回{model_count}个月"
            )
            if reason not in review_reasons:
                review_reasons.append(reason)
            if reason not in task_review_reasons:
                task_review_reasons.append(reason)
            needs_review = True

        start_month, end_month = _relative_month_range(
            application_year,
            application_month,
            effective_count,
        )
        if (
            group.start_month
            and group.end_month
            and (group.start_month != start_month or group.end_month != end_month)
        ):
            warning = (
                "模型返回的相对起止月份已由程序纠正："
                f"{group.start_month} 至 {group.end_month} → "
                f"{start_month} 至 {end_month}"
            )
            if warning not in warnings:
                warnings.append(warning)
            if warning not in task_warnings:
                task_warnings.append(warning)

        groups.append(
            replace(
                group,
                start_month=start_month,
                end_month=end_month,
                relative_month_count=effective_count,
                needs_review=needs_review,
                review_reasons=tuple(review_reasons),
                warnings=tuple(warnings),
            )
        )

    return replace(
        extraction,
        groups=tuple(groups),
        needs_review=extraction.needs_review
        or any(group.needs_review for group in groups),
        review_reasons=tuple(task_review_reasons),
        warnings=tuple(task_warnings),
    )


def _application_year_month(value: str) -> tuple[int, int]:
    try:
        parsed = date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError) as exc:
        raise AiResponseInvalidError(
            "ERP 申请日期格式无效，无法计算相对月份",
            details=f"application_date={value}",
        ) from exc
    return parsed.year, parsed.month


def _relative_month_range(
    application_year: int,
    application_month: int,
    month_count: int,
) -> tuple[str, str]:
    application_index = application_year * 12 + application_month - 1
    end_index = application_index - 1
    start_index = end_index - month_count + 1
    return _month_from_index(start_index), _month_from_index(end_index)


def _month_from_index(index: int) -> str:
    year, zero_based_month = divmod(index, 12)
    return f"{year:04d}-{zero_based_month + 1:02d}"


def _relative_month_count_from_expression(expression: str) -> int | None:
    normalized = re.sub(r"\s+", "", expression)
    if not normalized:
        return None
    if "半年" in normalized:
        return 6

    chinese_number = "一二两三四五六七八九十"
    year_count = _matched_period_number(
        normalized,
        rf"([0-9]+|[{chinese_number}]+)年",
    )
    month_count = _matched_period_number(
        normalized,
        rf"([0-9]+|[{chinese_number}]+)个?月(?:内)?",
    )
    if year_count:
        extra_months = 6 if "年半" in normalized else month_count or 0
        return year_count * 12 + extra_months
    return month_count


def _matched_period_number(value: str, pattern: str) -> int | None:
    match = re.search(pattern, value)
    if not match:
        return None
    raw_number = match.group(1)
    if raw_number.isdigit():
        number = int(raw_number)
        return number if number > 0 else None
    return _chinese_positive_integer(raw_number)


def _chinese_positive_integer(value: str) -> int | None:
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if "十" in value:
        tens, ones = value.split("十", 1)
        tens_value = digits.get(tens, 1) if tens else 1
        ones_value = digits.get(ones, 0) if ones else 0
        return tens_value * 10 + ones_value
    return digits.get(value)


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
