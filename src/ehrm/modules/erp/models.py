from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import os
from pathlib import Path

from ehrm.core.exceptions import ConfigurationError
from ehrm.core.settings import ErpSettings


@dataclass(frozen=True, slots=True)
class ErpCredentials:
    username: str
    password: str

    @classmethod
    def from_environment(cls, settings: ErpSettings) -> "ErpCredentials":
        username = os.environ.get(settings.username_env, "").strip()
        password = os.environ.get(settings.password_env, "")
        if not username or not password:
            raise ConfigurationError(
                "ERP 账号或密码未配置",
                details=(
                    f"请设置环境变量 {settings.username_env} 和 "
                    f"{settings.password_env}"
                ),
            )
        return cls(username=username, password=password)


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
