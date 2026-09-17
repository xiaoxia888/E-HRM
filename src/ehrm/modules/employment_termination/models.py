from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from ehrm.core.exceptions import QueryValidationError


_IDENTITY_PATTERN = re.compile(r"^(?:\d{15}|\d{17}[0-9Xx])$")


def _normalized_reason_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value)).removeprefix("string:")


class EmploymentTerminationReason(StrEnum):
    """退工原因编码，以智慧人社页面 option 的值为准。"""

    CONTRACT_EXPIRED = "6301"
    EMPLOYER_TERMINATED_CONTRACT = "6303"
    MUTUAL_AGREEMENT = "6304"
    EMPLOYEE_TERMINATED_CONTRACT = "6305"
    ENTERPRISE_BANKRUPTCY = "6306"
    WENT_ABROAD = "6307"
    IMPRISONMENT = "6309"
    RETIREMENT_BENEFIT_APPLICATION = "6313"
    DEATH_OR_MISSING = "6315"
    ORGANIZATIONAL_TRANSFER = "6316"
    ENTERPRISE_LAYOFF = "6317"
    ENTERPRISE_CLOSURE = "6323"
    DISABILITY_ALLOWANCE_APPLICATION = "6328"

    @property
    def display_name(self) -> str:
        return _TERMINATION_REASON_NAMES[self]

    @classmethod
    def parse(cls, value: object) -> "EmploymentTerminationReason":
        if isinstance(value, cls):
            return value
        normalized = _normalized_reason_text(value)
        for reason in cls:
            if normalized in {
                reason.value,
                _normalized_reason_text(reason.display_name),
            }:
                return reason
        available = "、".join(
            f"{reason.display_name}({reason.value})" for reason in cls
        )
        raise QueryValidationError(
            f"不支持的退工原因：{str(value).strip() or '空值'}",
            details=f"可用退工原因：{available}",
        )


_TERMINATION_REASON_NAMES = {
    EmploymentTerminationReason.CONTRACT_EXPIRED: "合同期满",
    EmploymentTerminationReason.EMPLOYER_TERMINATED_CONTRACT: "单位解除合同",
    EmploymentTerminationReason.MUTUAL_AGREEMENT: "双方协商一致解除",
    EmploymentTerminationReason.EMPLOYEE_TERMINATED_CONTRACT: "个人解除合同",
    EmploymentTerminationReason.ENTERPRISE_BANKRUPTCY: "企业破产",
    EmploymentTerminationReason.WENT_ABROAD: "出国",
    EmploymentTerminationReason.IMPRISONMENT: "服刑",
    EmploymentTerminationReason.RETIREMENT_BENEFIT_APPLICATION: (
        "申请养老待遇核定（或达到法定退休年龄）"
    ),
    EmploymentTerminationReason.DEATH_OR_MISSING: "死亡或失踪",
    EmploymentTerminationReason.ORGANIZATIONAL_TRANSFER: "组织调动",
    EmploymentTerminationReason.ENTERPRISE_LAYOFF: "企业裁员",
    EmploymentTerminationReason.ENTERPRISE_CLOSURE: "企业关闭或企业撤销、解散",
    EmploymentTerminationReason.DISABILITY_ALLOWANCE_APPLICATION: "申领病残津贴",
}


@dataclass(frozen=True, slots=True)
class EmploymentTerminationItem:
    """One object supplied by Excel today or a platform API in the future."""

    identity_number: str
    termination_reason: EmploymentTerminationReason | str
    source_index: int = 0

    def normalized(self) -> "EmploymentTerminationItem":
        identity = str(self.identity_number).strip().upper()
        prefix = f"第 {self.source_index} 条" if self.source_index > 0 else "退保数据"
        if not _IDENTITY_PATTERN.fullmatch(identity):
            raise QueryValidationError(f"{prefix}身份证号格式不正确")
        try:
            reason = EmploymentTerminationReason.parse(self.termination_reason)
        except QueryValidationError as exc:
            raise QueryValidationError(
                f"{prefix}{exc.message}", details=exc.details
            ) from exc
        return EmploymentTerminationItem(
            identity_number=identity,
            termination_reason=reason,
            source_index=self.source_index,
        )


@dataclass(frozen=True, slots=True)
class EmploymentTerminationPreparation:
    """Describes a completed form-fill run. It never implies submission."""

    items: tuple[EmploymentTerminationItem, ...]
    results: tuple["EmploymentTerminationItemResult", ...]
    city_code: str
    city_name: str
    submitted: bool = False

    @property
    def prepared_count(self) -> int:
        return sum(result.success for result in self.results)

    @property
    def failed_count(self) -> int:
        return len(self.results) - self.prepared_count

    @property
    def total_count(self) -> int:
        return len(self.results)


@dataclass(frozen=True, slots=True)
class EmploymentTerminationItemResult:
    """Row-level result returned by the reusable object-array service."""

    item: EmploymentTerminationItem
    success: bool
    code: str
    message: str = ""

    @property
    def source_index(self) -> int:
        return self.item.source_index


def normalize_termination_items(
    items: list[EmploymentTerminationItem]
    | tuple[EmploymentTerminationItem, ...],
) -> tuple[EmploymentTerminationItem, ...]:
    if not items:
        raise QueryValidationError("没有需要录入的退保数据")
    normalized = tuple(item.normalized() for item in items)
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in normalized:
        if item.identity_number in seen:
            duplicates.append(item.identity_number)
        seen.add(item.identity_number)
    if duplicates:
        raise QueryValidationError(
            "退保数据中身份证号重复",
            details="、".join(dict.fromkeys(duplicates)),
        )
    return normalized
