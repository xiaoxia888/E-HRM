from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ehrm.core.exceptions import QueryValidationError


_MONTH_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])$")


def _month_value(value: str) -> int:
    match = _MONTH_PATTERN.fullmatch(value)
    if not match:
        raise QueryValidationError(f"年月格式错误：{value}，正确格式为 YYYY-MM")
    return int(match.group("year")) * 12 + int(match.group("month"))


@dataclass(frozen=True, slots=True)
class RightsStatementQuery:
    start_month: str
    end_month: str
    insurance_type: str
    employee_name: str
    output_dir: Path

    def validate(self) -> None:
        start = _month_value(self.start_month)
        end = _month_value(self.end_month)
        if start > end:
            raise QueryValidationError("起始年月不能晚于结束年月")
        if not self.insurance_type.strip():
            raise QueryValidationError("险种类型不能为空")
        if not self.employee_name.strip():
            raise QueryValidationError("姓名不能为空")

    @property
    def fallback_filename(self) -> str:
        return (
            f"{self.employee_name}_{self.insurance_type}_"
            f"{self.start_month.replace('-', '')}-{self.end_month.replace('-', '')}_权益单.pdf"
        )

