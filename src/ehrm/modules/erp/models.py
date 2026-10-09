from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ErpCredentials:
    username: str
    password: str


class ErpTaskStatus(IntEnum):
    NEW = 0
    PENDING_SUBMISSION = 15
    IN_APPROVAL = 20
    EFFECTIVE = 35
    TERMINATED = 40
    APPROVED = 50

    @property
    def label(self) -> str:
        return {
            ErpTaskStatus.NEW: "新增",
            ErpTaskStatus.PENDING_SUBMISSION: "待送审",
            ErpTaskStatus.IN_APPROVAL: "审批中",
            ErpTaskStatus.EFFECTIVE: "生效",
            ErpTaskStatus.TERMINATED: "终止",
            ErpTaskStatus.APPROVED: "批准",
        }[self]

    @classmethod
    def display(cls, value: object) -> str:
        try:
            status = cls(int(str(value)))
        except (TypeError, ValueError):
            text = str(value or "").strip()
            return text or "未知"
        return f"{status.value}（{status.label}）"


@dataclass(frozen=True, slots=True)
class ErpApplicationRecord:
    id: str
    code: str
    name: str
    status: object | None = None


@dataclass(frozen=True, slots=True)
class ErpTaskRecord:
    """A normalized human-resource transaction returned by the ERP grid."""

    id: str
    code: str
    initiated_date: str
    title: str
    description: str
    transaction_type: str
    status: str
    originator: str
    department: str
    # 保留接口原始字段用于同步溯源；不参与正常日志表示或记录比较。
    raw_data: dict[str, object] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ErpTaskQueryResult:
    transaction_type: str
    records: tuple[ErpTaskRecord, ...]
    total_count: int
    pages_fetched: int
    status: ErpTaskStatus | None = None
    statuses: tuple[ErpTaskStatus, ...] = ()
    application_code: str = ""
    start_date: str = ""
    end_date: str = ""


@dataclass(frozen=True, slots=True)
class ErpPersonRecord:
    """A person returned by the ERP human-account certificate view."""

    id: str
    employee_code: str
    name: str
    identity_number: str
    department: str
    company: str
    status: str
    is_quit: str
    phone: str = ""


@dataclass(frozen=True, slots=True)
class ErpAttachmentRecord:
    id: str
    folder_id: str
    name: str
    extension: str
    size: int
    md5: str
    server_url: str


@dataclass(frozen=True, slots=True)
class ErpUploadResult:
    application: ErpApplicationRecord
    attachment: ErpAttachmentRecord
    source_file: Path
    chunks: int
