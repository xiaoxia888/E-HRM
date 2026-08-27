from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from ehrm.core.exceptions import QueryValidationError


_MONTH_PATTERN = re.compile(r"\d{6}")
_BUSINESS_NO_PATTERN = re.compile(r"\d{16}")


def _normalize_month(value: str, label: str) -> str:
    normalized = value.strip()
    if not _MONTH_PATTERN.fullmatch(normalized):
        raise QueryValidationError(f"{label}必须使用 YYYYMM 格式")
    month = int(normalized[4:])
    if not 1 <= month <= 12:
        raise QueryValidationError(f"{label}月份必须在 01 到 12 之间")
    return normalized


@dataclass(frozen=True, slots=True)
class PersonQueryRequest:
    identity_number: str
    start_month: str
    end_month: str
    name: str = ""
    organization_id: str | None = None
    page_number: int = 1
    page_size: int | None = None

    def to_payload(
        self,
        *,
        api_code: str,
        default_page_size: int,
    ) -> dict[str, object]:
        identity_number = self.identity_number.strip().upper()
        name = self.name.strip()
        if not identity_number and not name:
            raise QueryValidationError("身份证号码和姓名不能同时为空")
        start_month = _normalize_month(self.start_month, "开始日期")
        end_month = _normalize_month(self.end_month, "截止日期")
        if start_month > end_month:
            raise QueryValidationError("开始日期不能晚于截止日期")
        if self.page_number < 1:
            raise QueryValidationError("页码必须大于 0")
        page_size = (
            default_page_size if self.page_size is None else self.page_size
        )
        if page_size < 1:
            raise QueryValidationError("每页数量必须大于 0")

        return {
            "aac002": identity_number,
            "aac003": name,
            "apiCode": api_code,
            "aaf001": self.organization_id,
            "pageNumber": self.page_number,
            "pageSize": page_size,
            "aae003s": start_month,
            "aae003e": end_month,
        }


@dataclass(frozen=True, slots=True)
class PersonRecord:
    person_id: str
    identity_number: str
    name: str


@dataclass(frozen=True, slots=True)
class QueryPageInfo:
    api_code: str
    page_number: int
    page_size: int
    total_page: int
    total_count: int
    error_info: str | None


@dataclass(frozen=True, slots=True)
class PersonQueryResult:
    page: QueryPageInfo
    records: tuple[PersonRecord, ...]


class InsuranceCode(str, Enum):
    """Insurance codes accepted by the rights-statement print API."""

    PENSION = "110"
    WORK_INJURY = "410"
    UNEMPLOYMENT = "210"

    @property
    def display_name(self) -> str:
        return {
            InsuranceCode.PENSION: "养老",
            InsuranceCode.WORK_INJURY: "工伤",
            InsuranceCode.UNEMPLOYMENT: "失业",
        }[self]

    @classmethod
    def from_display_name(cls, value: str) -> "InsuranceCode":
        normalized = value.strip()
        mapping = {
            item.display_name: item
            for item in cls
        }
        try:
            return mapping[normalized]
        except KeyError as exc:
            raise QueryValidationError(
                "险种只能选择养老、工伤或失业"
            ) from exc


@dataclass(frozen=True, slots=True)
class RightsBillPrintRequest:
    start_month: str
    end_month: str
    insurance: InsuranceCode
    person_ids: tuple[str, ...]
    organization_id: str | None = None

    def to_payload(self, *, business_no: str) -> dict[str, object]:
        start_month = _normalize_month(self.start_month, "开始日期")
        end_month = _normalize_month(self.end_month, "截止日期")
        if start_month > end_month:
            raise QueryValidationError("开始日期不能晚于截止日期")
        normalized_business_no = business_no.strip()
        if not _BUSINESS_NO_PATTERN.fullmatch(normalized_business_no):
            raise QueryValidationError("打印业务流水号必须是 16 位数字")
        person_ids = tuple(
            person_id.strip()
            for person_id in self.person_ids
            if person_id.strip()
        )
        if not person_ids:
            raise QueryValidationError("打印人员编号不能为空")
        if len(set(person_ids)) != len(person_ids):
            raise QueryValidationError("打印人员编号不能重复")
        if not isinstance(self.insurance, InsuranceCode):
            raise QueryValidationError("险种代码无效")

        return {
            "businessNo": normalized_business_no,
            "queryStartYMprint": start_month,
            "queryEndYMprint": end_month,
            "insuranceCode": self.insurance.value,
            "aab365": self.organization_id,
            "personUniqueIdList": list(person_ids),
        }


@dataclass(frozen=True, slots=True)
class RightsBillPdf:
    content: bytes
    insurance: InsuranceCode
    person_count: int
