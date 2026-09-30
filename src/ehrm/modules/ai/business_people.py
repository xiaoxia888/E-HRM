from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ehrm.core.exceptions import AiResponseInvalidError
from ehrm.modules.erp.models import ErpTaskRecord


_IDENTITY_PATTERN = re.compile(r"(?:\d{15}|\d{17}[0-9X])\Z")

BUSINESS_PEOPLE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["people"],
    "properties": {
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "identity_number", "evidence"],
                "properties": {
                    "name": {"type": "string"},
                    "identity_number": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}


@dataclass(frozen=True, slots=True)
class ExtractedBusinessPerson:
    name: str
    identity_number: str
    evidence: str


@dataclass(frozen=True, slots=True)
class BusinessPeopleExtraction:
    people: tuple[ExtractedBusinessPerson, ...]


def validate_business_people_payload(
    payload: object,
    record: ErpTaskRecord,
) -> BusinessPeopleExtraction:
    if not isinstance(payload, dict) or set(payload) != {"people"}:
        raise AiResponseInvalidError("人员解析结果字段不正确")
    raw_people = payload["people"]
    if not isinstance(raw_people, list):
        raise AiResponseInvalidError("人员解析结果 people 必须是数组")
    people: list[ExtractedBusinessPerson] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_people:
        if not isinstance(raw, dict) or set(raw) != {
            "name", "identity_number", "evidence"
        }:
            raise AiResponseInvalidError("人员解析结果中的人员字段不正确")
        if not all(isinstance(value, str) for value in raw.values()):
            raise AiResponseInvalidError("人员解析字段必须是文本")
        name = raw["name"].strip()
        identity = raw["identity_number"].strip().upper()
        evidence = raw["evidence"].strip()
        if not name or not any(name in source for source in (record.title, record.description)):
            raise AiResponseInvalidError("解析姓名必须出现在申请原文中")
        if not evidence or not any(
            evidence in source for source in (record.title, record.description)
        ) or name not in evidence:
            raise AiResponseInvalidError("人员解析依据必须包含姓名且来自申请原文")
        if identity and (
            not _IDENTITY_PATTERN.fullmatch(identity)
            or identity not in evidence.upper()
        ):
            raise AiResponseInvalidError("身份证必须在人员解析依据中明确出现")
        key = (name, identity)
        if key not in seen:
            people.append(ExtractedBusinessPerson(name, identity, evidence))
            seen.add(key)
    return BusinessPeopleExtraction(tuple(people))
