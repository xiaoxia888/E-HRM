from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ErpApplicationRecord:
    id: str
    code: str
    name: str
    status: object | None = None


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
