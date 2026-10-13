from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import re

from ehrm.core.exceptions import QueryValidationError


_IDENTITY = re.compile(r"(?:\d{15}|\d{17}[0-9X])")
_MOBILE = re.compile(r"1[3-9]\d{9}")


class MedicalStage(StrEnum):
    COLLECTION = "collection"
    ENROLLMENT = "enrollment"


@dataclass(frozen=True, slots=True)
class MedicalPreSubmitItem:
    identity_number: str
    name: str = ""
    mobile: str = ""
    nation: str = ""
    document_start_date: date | None = None
    document_end_date: date | None = None
    enrollment_date: date | None = None
    source_index: int = 2

    def normalized(self, stage: MedicalStage) -> "MedicalPreSubmitItem":
        identity = self.identity_number.strip().upper()
        prefix = f"第 {self.source_index} 行"
        if not _IDENTITY.fullmatch(identity):
            raise QueryValidationError(f"{prefix}身份证号格式不正确")
        name = self.name.strip()
        mobile = self.mobile.strip()
        nation = self.nation.strip()
        if stage is MedicalStage.COLLECTION and not name:
            raise QueryValidationError(f"{prefix}基础信息采集缺少姓名")
        if mobile and not _MOBILE.fullmatch(mobile):
            raise QueryValidationError(f"{prefix}联系电话必须为 11 位中国大陆手机号")
        if stage is MedicalStage.ENROLLMENT and (not mobile or self.enrollment_date is None):
            raise QueryValidationError(f"{prefix}参保登记须提供参保日期和联系电话")
        if (
            self.document_start_date is not None
            and self.document_end_date is not None
            and self.document_start_date > self.document_end_date
        ):
            raise QueryValidationError(f"{prefix}证件有效期起始日期晚于截止日期")
        return MedicalPreSubmitItem(
            identity, name, mobile, nation,
            self.document_start_date, self.document_end_date,
            self.enrollment_date, self.source_index,
        )
