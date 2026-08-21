from __future__ import annotations

from ehrm.core.exceptions import ConfigurationError
from ehrm.core.preferences import UserPreferencesStore
from ehrm.core.settings import AppSettings
from ehrm.modules.erp.credential_store import ErpCredentialStore
from ehrm.modules.erp.models import ErpCredentials


def resolve_erp_credentials(settings: AppSettings) -> ErpCredentials:
    preferences = UserPreferencesStore(
        settings.browser.user_data_dir.parent / "preferences.json"
    ).load()
    username = preferences.erp_username.strip()
    password = ErpCredentialStore().load_password(username) if username else None
    if username and password:
        return ErpCredentials(username=username, password=password)
    if username:
        raise ConfigurationError(
            "ERP 已保存账号但未找到对应密码",
            details="请在“系统设置 → 账户与连接”中重新输入密码并保存。",
        )
    try:
        return ErpCredentials.from_environment(settings.erp)
    except ConfigurationError as exc:
        raise ConfigurationError(
            "ERP 账号或密码未配置",
            details="请先在“系统设置 → 账户与连接”中保存 ERP 账号。",
        ) from exc
