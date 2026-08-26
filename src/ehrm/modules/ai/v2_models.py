from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import re
from typing import Any

from ehrm.core.exceptions import AiResponseInvalidError
from ehrm.modules.ai.models import PrintMode, RequirementType


_MONTH_PATTERN = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])")
_IDENTITY_PATTERN = re.compile(r"(?:\d{15}|\d{17}[0-9X])")


class SemanticTimeType(StrEnum):
    EXPLICIT_RANGE = "explicit_range"
    EXPLICIT_MONTH = "explicit_month"
    RELATIVE_MONTHS = "relative_months"
    CURRENT_YEAR = "current_year"
    PREVIOUS_YEAR = "previous_year"
    UNTIL_NOW = "until_now"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class SemanticPerson:
    name: str
    social_security_number: str | None
    birth_year_hint: int | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SemanticTime:
    time_type: str
    expression: str
    start_month: str | None
    end_month: str | None
    month_count: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.time_type,
            "expression": self.expression,
            "start_month": self.start_month,
            "end_month": self.end_month,
            "month_count": self.month_count,
        }


@dataclass(frozen=True, slots=True)
class SemanticPrintPlan:
    people: tuple[SemanticPerson, ...]
    benefit_category: str
    print_mode: str | None
    time: SemanticTime

    def as_dict(self) -> dict[str, Any]:
        return {
            "people": [person.as_dict() for person in self.people],
            "benefit_category": self.benefit_category,
            "print_mode": self.print_mode,
            "time": self.time.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class SemanticRequest:
    request_type: str
    source_text: str
    reason: str
    print_plan: SemanticPrintPlan | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.request_type,
            "source_text": self.source_text,
            "reason": self.reason,
            "print_plan": (
                self.print_plan.as_dict() if self.print_plan is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class SemanticExtraction:
    requests: tuple[SemanticRequest, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"requests": [request.as_dict() for request in self.requests]}


SEMANTIC_EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["requests"],
    "properties": {
        "requests": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "source_text", "reason", "print_plan"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [item.value for item in RequirementType],
                    },
                    "source_text": {"type": "string", "minLength": 1},
                    "reason": {"type": "string"},
                    "print_plan": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "required": [
                            "people",
                            "benefit_category",
                            "print_mode",
                            "time",
                        ],
                        "properties": {
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
                                    ],
                                    "properties": {
                                        "name": {"type": "string", "minLength": 1},
                                        "social_security_number": {
                                            "type": ["string", "null"],
                                            "pattern": (
                                                "^(?:[0-9]{15}|"
                                                "[0-9]{17}[0-9Xx])$"
                                            ),
                                        },
                                        "birth_year_hint": {
                                            "type": ["integer", "null"],
                                            "minimum": 1900,
                                            "maximum": 2099,
                                        },
                                    },
                                },
                            },
                            "benefit_category": {
                                "type": "string",
                                "enum": ["社保", "医保"],
                            },
                            "print_mode": {
                                "type": ["string", "null"],
                                "enum": [
                                    PrintMode.COMBINED.value,
                                    PrintMode.INDIVIDUAL.value,
                                    None,
                                ],
                            },
                            "time": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "type",
                                    "expression",
                                    "start_month",
                                    "end_month",
                                    "month_count",
                                ],
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": [
                                            item.value for item in SemanticTimeType
                                        ],
                                    },
                                    "expression": {"type": "string"},
                                    "start_month": {
                                        "type": ["string", "null"],
                                        "pattern": (
                                            "^[0-9]{4}-(0[1-9]|1[0-2])$"
                                        ),
                                    },
                                    "end_month": {
                                        "type": ["string", "null"],
                                        "pattern": (
                                            "^[0-9]{4}-(0[1-9]|1[0-2])$"
                                        ),
                                    },
                                    "month_count": {
                                        "type": ["integer", "null"],
                                        "minimum": 1,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
    },
}


def validate_semantic_extraction_payload(payload: object) -> SemanticExtraction:
    """Strictly validates the small V2 semantic model response."""

    if not isinstance(payload, dict) or set(payload) != {"requests"}:
        raise AiResponseInvalidError("V2 模型结果根节点只能包含 requests")
    raw_requests = payload["requests"]
    if not isinstance(raw_requests, list) or not raw_requests:
        raise AiResponseInvalidError("V2 模型结果 requests 必须是非空数组")

    requests: list[SemanticRequest] = []
    request_fields = {"type", "source_text", "reason", "print_plan"}
    for request_index, raw_request in enumerate(raw_requests, start=1):
        path = f"requests[{request_index}]"
        if not isinstance(raw_request, dict) or set(raw_request) != request_fields:
            raise AiResponseInvalidError(f"{path} 字段不正确")
        request_type_text = _required_text(raw_request["type"], f"{path}.type")
        try:
            request_type = RequirementType(request_type_text).value
        except ValueError as exc:
            raise AiResponseInvalidError(f"{path}.type 无效") from exc
        source_text = _required_text(
            raw_request["source_text"], f"{path}.source_text"
        )
        reason = _text(raw_request["reason"], f"{path}.reason")
        raw_plan = raw_request["print_plan"]
        if request_type == RequirementType.RIGHTS_STATEMENT.value:
            if reason:
                raise AiResponseInvalidError(f"{path} 可处理需求的 reason 必须为空")
            print_plan = _validate_print_plan(raw_plan, path)
        else:
            if not reason:
                raise AiResponseInvalidError(f"{path} 非打印需求必须说明原因")
            if raw_plan is not None:
                raise AiResponseInvalidError(f"{path} 非打印需求不得包含 print_plan")
            print_plan = None
        requests.append(
            SemanticRequest(
                request_type=request_type,
                source_text=source_text,
                reason=reason,
                print_plan=print_plan,
            )
        )
    return SemanticExtraction(requests=tuple(requests))


def _validate_print_plan(raw_plan: object, request_path: str) -> SemanticPrintPlan:
    path = f"{request_path}.print_plan"
    fields = {"people", "benefit_category", "print_mode", "time"}
    if not isinstance(raw_plan, dict) or set(raw_plan) != fields:
        raise AiResponseInvalidError(f"{path} 字段不正确")
    raw_people = raw_plan["people"]
    if not isinstance(raw_people, list) or not raw_people:
        raise AiResponseInvalidError(f"{path}.people 必须是非空数组")
    people: list[SemanticPerson] = []
    seen_people: set[tuple[str, str, int | None]] = set()
    person_fields = {"name", "social_security_number", "birth_year_hint"}
    for person_index, raw_person in enumerate(raw_people, start=1):
        person_path = f"{path}.people[{person_index}]"
        if not isinstance(raw_person, dict) or set(raw_person) != person_fields:
            raise AiResponseInvalidError(f"{person_path} 字段不正确")
        name = _required_text(raw_person["name"], f"{person_path}.name")
        identity = _identity(
            raw_person["social_security_number"],
            f"{person_path}.social_security_number",
        )
        birth_year_hint = _birth_year(
            raw_person["birth_year_hint"],
            f"{person_path}.birth_year_hint",
        )
        signature = (name, identity or "", birth_year_hint)
        if signature in seen_people:
            raise AiResponseInvalidError(f"{path} 内人员重复：{name}")
        seen_people.add(signature)
        people.append(
            SemanticPerson(
                name=name,
                social_security_number=identity,
                birth_year_hint=birth_year_hint,
            )
        )

    benefit_category = _required_text(
        raw_plan["benefit_category"],
        f"{path}.benefit_category",
    )
    if benefit_category not in {"社保", "医保"}:
        raise AiResponseInvalidError(f"{path}.benefit_category 无效")

    raw_print_mode = raw_plan["print_mode"]
    if raw_print_mode is None:
        print_mode = None
    else:
        try:
            print_mode = PrintMode(
                _required_text(raw_print_mode, f"{path}.print_mode")
            ).value
        except ValueError as exc:
            raise AiResponseInvalidError(f"{path}.print_mode 无效") from exc

    time = _validate_time(raw_plan["time"], path)
    return SemanticPrintPlan(
        people=tuple(people),
        benefit_category=benefit_category,
        print_mode=print_mode,
        time=time,
    )


def _validate_time(raw_time: object, plan_path: str) -> SemanticTime:
    path = f"{plan_path}.time"
    fields = {"type", "expression", "start_month", "end_month", "month_count"}
    if not isinstance(raw_time, dict) or set(raw_time) != fields:
        raise AiResponseInvalidError(f"{path} 字段不正确")
    time_type_text = _required_text(raw_time["type"], f"{path}.type")
    try:
        time_type = SemanticTimeType(time_type_text)
    except ValueError as exc:
        raise AiResponseInvalidError(f"{path}.type 无效") from exc
    expression = _text(raw_time["expression"], f"{path}.expression")
    start_month = _month(raw_time["start_month"], f"{path}.start_month")
    end_month = _month(raw_time["end_month"], f"{path}.end_month")
    month_count = _positive_int_or_none(
        raw_time["month_count"], f"{path}.month_count"
    )

    if time_type is SemanticTimeType.EXPLICIT_RANGE:
        if not start_month or not end_month or month_count is not None:
            raise AiResponseInvalidError(
                f"{path} 明确范围必须包含起止月份且 month_count=null"
            )
    elif time_type is SemanticTimeType.EXPLICIT_MONTH:
        if (
            not start_month
            or start_month != end_month
            or month_count is not None
        ):
            raise AiResponseInvalidError(
                f"{path} 单月的起止月份必须相同且 month_count=null"
            )
    elif time_type is SemanticTimeType.RELATIVE_MONTHS:
        if start_month or end_month or month_count is None:
            raise AiResponseInvalidError(
                f"{path} 相对时间只能填写 month_count"
            )
    elif time_type is SemanticTimeType.UNTIL_NOW:
        if end_month or month_count is not None:
            raise AiResponseInvalidError(
                f"{path} 至今条件只能选填 start_month"
            )
    elif start_month or end_month or month_count is not None:
        raise AiResponseInvalidError(
            f"{path} 的 {time_type.value} 不得填写月份或月数"
        )
    if start_month and end_month and start_month > end_month:
        raise AiResponseInvalidError(f"{path} 开始月份晚于结束月份")
    if time_type not in {SemanticTimeType.MISSING, SemanticTimeType.AMBIGUOUS}:
        if not expression:
            raise AiResponseInvalidError(f"{path}.expression 不能为空")
    return SemanticTime(
        time_type=time_type.value,
        expression=expression,
        start_month=start_month,
        end_month=end_month,
        month_count=month_count,
    )


def _text(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise AiResponseInvalidError(f"{path} 必须是字符串")
    return value.strip()


def _required_text(value: object, path: str) -> str:
    text = _text(value, path)
    if not text:
        raise AiResponseInvalidError(f"{path} 不能为空")
    return text


def _month(value: object, path: str) -> str | None:
    if value is None:
        return None
    text = _required_text(value, path)
    if not _MONTH_PATTERN.fullmatch(text):
        raise AiResponseInvalidError(f"{path} 必须是 YYYY-MM 或 null")
    return text


def _identity(value: object, path: str) -> str | None:
    if value is None:
        return None
    text = _required_text(value, path).upper()
    if not _IDENTITY_PATTERN.fullmatch(text):
        raise AiResponseInvalidError(f"{path} 必须是 15/18 位身份证或 null")
    return text


def _birth_year(value: object, path: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1900 <= value <= 2099:
        raise AiResponseInvalidError(f"{path} 必须是 1900 至 2099 的整数或 null")
    return value


def _positive_int_or_none(value: object, path: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AiResponseInvalidError(f"{path} 必须是正整数或 null")
    return value


def _string_tuple(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AiResponseInvalidError(f"{path} 必须是字符串数组")
    result: list[str] = []
    for index, item in enumerate(value, start=1):
        text = _required_text(item, f"{path}[{index}]")
        if text not in result:
            result.append(text)
    return tuple(result)
