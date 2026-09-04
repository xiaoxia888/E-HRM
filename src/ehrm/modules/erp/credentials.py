from __future__ import annotations

from ehrm.core.exceptions import ConfigurationError
from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.settings import AppSettings
from ehrm.modules.erp.models import ErpCredentials


def resolve_erp_credentials(settings: AppSettings) -> ErpCredentials:
    repository = AuthenticationRepository(settings.auth_database_path)
    saved = repository.get_default_account(SystemType.ERP)
    if saved is not None and saved.password:
        return ErpCredentials(username=saved.account, password=saved.password)
    if saved is not None:
        raise ConfigurationError("ERP 已保存账号但未找到对应密码")
    try:
        credentials = ErpCredentials.from_environment(settings.erp)
    except ConfigurationError as exc:
        raise ConfigurationError(
            "ERP 账号或密码未配置",
            details="请先在“系统设置 → 账户与连接”中保存 ERP 账号。",
        ) from exc
    repository.save_account(
        SystemType.ERP,
        credentials.username,
        credentials.password,
    )
    return credentials
