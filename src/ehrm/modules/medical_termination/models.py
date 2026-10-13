from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from ehrm.core.exceptions import QueryValidationError


MEDICAL_TERMINATION_REASONS = frozenset({
    "组织变更的其他情况",
    "人员中断缴费",
    "在职人员解除/终止劳动合同",
    "人员达到享受待遇条件",
    "人员调动",
    "其他原因中断缴费",
    "单位调动",
})

_IDENTITY_PATTERN = re.compile(r"^(?:\d{15}|\d{17}[0-9X])$")


@dataclass(frozen=True, slots=True)
class MedicalTerminationItem:
    identity_number: str
    reason: str
    termination_date: date
    pay_current_month: bool
    source_index: int = 0

    def normalized(self) -> "MedicalTerminationItem":
        identity = self.identity_number.strip().upper()
        prefix = f"第 {self.source_index} 行" if self.source_index else "医保停保"
        if not _IDENTITY_PATTERN.fullmatch(identity):
            raise QueryValidationError(f"{prefix}身份证号格式不正确")
        reason = self.reason.strip()
        if reason not in MEDICAL_TERMINATION_REASONS:
            raise QueryValidationError(
                f"{prefix}停保原因未在录制页面选项中：{reason or '空值'}",
                details="可用原因：" + "、".join(sorted(MEDICAL_TERMINATION_REASONS)),
            )
        return MedicalTerminationItem(
            identity_number=identity,
            reason=reason,
            termination_date=self.termination_date,
            pay_current_month=self.pay_current_month,
            source_index=self.source_index,
        )
