from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import StrEnum
import re
from collections.abc import Sequence

from ehrm.core.exceptions import EhrmError, QueryValidationError


_IDENTITY = re.compile(r"(?:\d{15}|\d{17}[0-9X])\Z")


def _key(value: object) -> str:
    return re.sub(r"\s+", "", str(value)).removeprefix("string:")


class _NamedCode(StrEnum):
    @property
    def display_name(self) -> str:
        raise NotImplementedError

    @classmethod
    def parse(cls, value: object):
        if isinstance(value, cls):
            return value
        normalized = _key(value)
        for member in cls:
            if normalized in {member.value, _key(member.display_name)}:
                return member
        available = "、".join(
            f"{member.display_name}({member.value})" for member in cls
        )
        raise QueryValidationError(
            f"不支持的{cls.field_name()}：{str(value).strip() or '空值'}",
            details=f"可用值：{available}",
        )

    @classmethod
    def field_name(cls) -> str:
        return "枚举值"


class ContractAddReason(_NamedCode):
    NEW = "1"
    RENEWAL = "3"

    @property
    def display_name(self) -> str:
        return {self.NEW: "新签", self.RENEWAL: "续签"}[self]

    @classmethod
    def field_name(cls) -> str:
        return "合同增加原因"


class ContractType(_NamedCode):
    FIXED_TERM = "41"
    OPEN_ENDED = "42"
    TASK_BASED = "43"

    @property
    def display_name(self) -> str:
        return {
            self.FIXED_TERM: "固定期限",
            self.OPEN_ENDED: "无固定期限",
            self.TASK_BASED: "完成一定工作任务",
        }[self]

    @classmethod
    def field_name(cls) -> str:
        return "合同类别"


class PositionType(_NamedCode):
    UNIT_LEADER = "01"
    MANAGER = "02"
    PROFESSIONAL = "03"
    PRODUCTION_TRANSPORT = "04"
    COMMERCIAL_SERVICE = "05"
    AGRICULTURE = "06"
    ORDINARY_EMPLOYEE = "07"

    @property
    def display_name(self) -> str:
        return {
            self.UNIT_LEADER: "单位负责人",
            self.MANAGER: "管理人员",
            self.PROFESSIONAL: "专业技术人员",
            self.PRODUCTION_TRANSPORT: "生产运输操作人员",
            self.COMMERCIAL_SERVICE: "商业和其他服务业",
            self.AGRICULTURE: "农林牧渔从业人员",
            self.ORDINARY_EMPLOYEE: "普通员工",
        }[self]

    @classmethod
    def field_name(cls) -> str:
        return "岗位工种"


class InsuredIdentity(_NamedCode):
    ENTERPRISE_EMPLOYEE = "101"

    @property
    def display_name(self) -> str:
        return "企业职工"

    @classmethod
    def field_name(cls) -> str:
        return "参保身份"


class EmploymentEnrollmentRowError(EhrmError):
    """A business/data problem limited to the current employee."""

    def __init__(self, message: str, *, reason_code: str, details: str | None = None) -> None:
        super().__init__(message, details=details)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class EmploymentEnrollmentItem:
    identity_number: str
    contract_add_reason: ContractAddReason | str
    contract_type: ContractType | str
    contract_start_date: date | datetime | str
    contract_end_date: date | datetime | str | None
    position_type: PositionType | str
    monthly_wage: Decimal | int | float | str | None = None
    insured_identity: InsuredIdentity | str = InsuredIdentity.ENTERPRISE_EMPLOYEE
    source_index: int = 0

    def normalized(self) -> "EmploymentEnrollmentItem":
        prefix = f"第 {self.source_index} 行" if self.source_index > 0 else "参保数据"
        identity = str(self.identity_number).strip().upper()
        if not _IDENTITY.fullmatch(identity):
            raise QueryValidationError(f"{prefix}身份证号格式不正确")
        try:
            reason = ContractAddReason.parse(self.contract_add_reason)
            contract_type = ContractType.parse(self.contract_type)
            position = PositionType.parse(self.position_type)
            insured = InsuredIdentity.parse(self.insured_identity)
        except QueryValidationError as exc:
            raise QueryValidationError(f"{prefix}{exc.message}", details=exc.details) from exc
        start = _parse_date(self.contract_start_date, f"{prefix}劳动合同开始日期")
        end: date | None
        if contract_type is ContractType.OPEN_ENDED:
            end = None
        else:
            end = _parse_date(self.contract_end_date, f"{prefix}劳动合同终止日期")
            if end < start:
                raise QueryValidationError(f"{prefix}劳动合同终止日期不能早于开始日期")

        wage: Decimal | None = None
        if reason is ContractAddReason.NEW:
            wage = _parse_wage(self.monthly_wage, prefix)
        return EmploymentEnrollmentItem(
            identity_number=identity,
            contract_add_reason=reason,
            contract_type=contract_type,
            contract_start_date=start,
            contract_end_date=end,
            position_type=position,
            monthly_wage=wage,
            insured_identity=insured,
            source_index=self.source_index,
        )


def _parse_date(value: date | datetime | str | None, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise QueryValidationError(f"{label}必须使用 YYYY-MM-DD 格式") from exc


def _parse_wage(value: Decimal | int | float | str | None, prefix: str) -> Decimal:
    if isinstance(value, bool):
        raise QueryValidationError(f"{prefix}月缴费工资必须是数值")
    text = str(value if value is not None else "").strip()
    try:
        wage = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise QueryValidationError(f"{prefix}月缴费工资必须是数值") from exc
    if not wage.is_finite() or wage < 0:
        raise QueryValidationError(f"{prefix}月缴费工资必须是大于等于 0 的有限数值")
    # The Jiangsu HRSS wage field accepts one decimal place. Normalize before
    # browser entry so the site cannot silently truncate a two-decimal amount.
    return wage.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def normalize_enrollment_items(
    items: Sequence[EmploymentEnrollmentItem],
) -> tuple[EmploymentEnrollmentItem, ...]:
    normalized = tuple(item.normalized() for item in items)
    if not normalized:
        raise QueryValidationError("没有需要录入的参保数据")
    identities = [item.identity_number for item in normalized]
    duplicates = list(dict.fromkeys(value for value in identities if identities.count(value) > 1))
    if duplicates:
        raise QueryValidationError("参保数据中身份证号重复", details="、".join(duplicates))
    return normalized


@dataclass(frozen=True, slots=True)
class EmploymentEnrollmentResult:
    item: EmploymentEnrollmentItem
    success: bool
    code: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class EmploymentEnrollmentPreparation:
    items: tuple[EmploymentEnrollmentItem, ...]
    results: tuple[EmploymentEnrollmentResult, ...]
    city_code: str = "320100"
    city_name: str = "南京"
    submitted: bool = False

    @property
    def total_count(self) -> int:
        return len(self.results)

    @property
    def prepared_count(self) -> int:
        return sum(result.success for result in self.results)
