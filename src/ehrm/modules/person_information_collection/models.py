from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Sequence

from ehrm.core.exceptions import EhrmError, QueryValidationError


_IDENTITY = re.compile(r"(?:\d{15}|\d{17}[0-9X])\Z")
_MOBILE = re.compile(r"1\d{10}\Z")


class PersonInformationRowError(EhrmError):
    """A data/business problem limited to one person in a batch."""

    def __init__(self, message: str, *, reason_code: str, details: str | None = None) -> None:
        super().__init__(message, details=details)
        self.reason_code = reason_code


def address_level_for_household(label: str) -> int:
    """Returns 0/3/5 from the option label selected on the live form."""
    normalized = re.sub(r"\s+", "", str(label))
    if any(token in normalized for token in ("香港", "澳门", "台湾", "外国")):
        return 0
    if "本省" in normalized:
        return 5
    if "外省" in normalized:
        return 3
    raise PersonInformationRowError(
        f"无法识别户籍性质对应的地址规则：{str(label).strip() or '空值'}",
        reason_code="HOUSEHOLD_TYPE_UNSUPPORTED",
    )


@dataclass(frozen=True, slots=True)
class PersonInformationItem:
    """One form's data. Platform callers pass these objects, never workbooks."""

    identity_number: str
    name: str
    mobile: str
    nation: str
    household_type: str
    address: tuple[str, ...]
    source_index: int = 0

    def normalized(self) -> "PersonInformationItem":
        prefix = f"第 {self.source_index} 行" if self.source_index > 0 else "采集数据"
        identity = str(self.identity_number).strip().upper()
        name = str(self.name).strip()
        mobile = str(self.mobile).strip()
        nation = str(self.nation).strip()
        household = str(self.household_type).strip()
        raw_address = tuple(str(part).strip() for part in self.address)
        if len(raw_address) > 5:
            raise QueryValidationError(f"{prefix}户籍地址最多支持五级")
        address_parts = list(raw_address)
        while address_parts and not address_parts[-1]:
            address_parts.pop()
        address = tuple(address_parts)
        if not _IDENTITY.fullmatch(identity):
            raise QueryValidationError(f"{prefix}身份证号格式不正确")
        if not name:
            raise QueryValidationError(f"{prefix}姓名不能为空")
        if not _MOBILE.fullmatch(mobile):
            raise QueryValidationError(f"{prefix}手机号格式不正确")
        if not nation:
            raise QueryValidationError(f"{prefix}民族不能为空")
        if not household:
            raise QueryValidationError(f"{prefix}户籍性质不能为空")
        if any(not part for part in address):
            raise QueryValidationError(f"{prefix}户籍地址中间层级不能为空")
        return PersonInformationItem(
            identity, name, mobile, nation, household, address, self.source_index
        )


def normalize_items(items: Sequence[PersonInformationItem]) -> tuple[PersonInformationItem, ...]:
    normalized = tuple(item.normalized() for item in items)
    if not normalized:
        raise QueryValidationError("没有可录入的人员基础信息")
    seen: set[str] = set()
    for item in normalized:
        if item.identity_number in seen:
            raise QueryValidationError(f"身份证号重复：{item.identity_number}")
        seen.add(item.identity_number)
    return normalized


@dataclass(frozen=True, slots=True)
class PersonInformationResult:
    item: PersonInformationItem
    success: bool
    code: str = "SUCCESS"
    message: str = ""


@dataclass(frozen=True, slots=True)
class PersonInformationPreparation:
    items: tuple[PersonInformationItem, ...]
    results: tuple[PersonInformationResult, ...]
    city_code: str
    city_name: str
    submitted: bool = False

    @property
    def prepared_count(self) -> int:
        return sum(result.success for result in self.results)

    @property
    def total_count(self) -> int:
        return len(self.items)
