from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import shutil

from ehrm.core.auth_repository import AuthenticationRepository, SystemAccount, SystemType
from ehrm.core.preferences import UserPreferences, UserPreferencesStore
from ehrm.core.settings import AppSettings, select_ai_model


class WebSettingsService:
    """Shares accounts and user preferences with the existing desktop UI."""

    def __init__(self, settings: AppSettings, runtime_root: Path) -> None:
        self.base_settings = settings
        self.runtime_root = runtime_root
        self.repository = AuthenticationRepository(settings.auth_database_path)
        self.preferences_store = UserPreferencesStore(
            settings.browser.user_data_dir.parent / "preferences.json"
        )

    def preferences(self) -> UserPreferences:
        return self.preferences_store.load()

    def preference_payload(self) -> dict[str, object]:
        preferences = self.preferences()
        selected = self.runtime_settings(preferences)
        return {
            **asdict(preferences),
            "ai_model_options": [
                {
                    "value": item.profile_id.value,
                    "label": item.display_name,
                    "model": item.model,
                    "reasoning_modes": list(item.reasoning_modes),
                    "default_reasoning_mode": item.default_reasoning_mode,
                    "native_context_length": item.native_context_length,
                    "num_ctx": item.num_ctx,
                    "num_predict": item.num_predict,
                    "request_timeout_seconds": item.request_timeout_seconds,
                    "keep_alive": item.keep_alive,
                    "source_url": item.source_url,
                }
                for item in self.base_settings.ai_models
            ],
            "active_ai_model": selected.ai.profile_id.value,
            "active_reasoning_mode": selected.ai.default_reasoning_mode,
            "runtime_path": str(self.runtime_root),
            "logs_path": str(self.runtime_root / "logs"),
        }

    def clear_temporary_files(self) -> int:
        targets = (
            self.runtime_root / "screenshots",
            self.base_settings.browser.user_data_dir.parent / "screenshots",
            self.base_settings.browser.user_data_dir.parent / "session-state.json",
        )
        removed = 0
        for target in dict.fromkeys(path.resolve() for path in targets):
            if target.is_dir():
                removed += sum(1 for item in target.rglob("*") if item.is_file())
                shutil.rmtree(target)
            elif target.is_file():
                target.unlink()
                removed += 1
        return removed

    def save_preferences(self, preferences: UserPreferences) -> UserPreferences:
        self.preferences_store.save(preferences)
        return self.preferences_store.load()

    def save_account(
        self,
        system_type: SystemType,
        *,
        account_id: int | None = None,
        account: str,
        secondary_account: str = "",
        password: str = "",
        display_name: str = "",
    ) -> SystemAccount:
        selected = None
        if account_id is not None:
            selected = next(
                (
                    item
                    for item in self.repository.list_accounts(system_type)
                    if item.id == account_id
                ),
                None,
            )
            if selected is None:
                raise ValueError("原账号已不存在，请刷新页面后重试")
        normalized_account = account.strip() or (selected.account if selected else "")
        normalized_secondary = secondary_account.strip() or (
            selected.secondary_account if selected else ""
        )
        if not normalized_account:
            raise ValueError("登录账号不能为空")
        if system_type is SystemType.JSHRSS and not normalized_secondary:
            raise ValueError("江苏智慧人社证件号码或移动电话不能为空")

        existing = selected or self.repository.get_default_account(system_type)
        same_identity = bool(
            existing
            and existing.account == normalized_account
            and existing.secondary_account == normalized_secondary
        )
        resolved_password = password or (existing.password if same_identity else "")
        if not resolved_password:
            raise ValueError("请输入密码；更换账号时不能沿用原账号密码")
        saved = self.repository.save_account(
            system_type,
            normalized_account,
            resolved_password,
            secondary_account=normalized_secondary,
            display_name=display_name.strip() or (existing.display_name if existing else ""),
        )
        if existing is not None and existing.id == saved.id and password:
            self.repository.delete_session(saved.id)
        return saved

    def account(self, account_id: int, system_type: SystemType) -> SystemAccount:
        account = next(
            (
                item
                for item in self.repository.list_accounts(system_type)
                if item.id == account_id
            ),
            None,
        )
        if account is None:
            raise ValueError("所选账号不存在，请刷新系统设置后重试")
        if not account.account or not account.password:
            raise ValueError("所选账号信息不完整，请先在系统设置中补充")
        if system_type is SystemType.JSHRSS and not account.secondary_account:
            raise ValueError("所选智慧人社账号缺少证件号码或移动电话")
        return account

    def runtime_settings(
        self,
        preferences: UserPreferences | None = None,
        *,
        rights_account: SystemAccount | None = None,
        erp_account: SystemAccount | None = None,
    ) -> AppSettings:
        preferences = preferences or self.preferences()
        speed_ranges = {
            "fast": (500, 1000),
            "standard": (
                self.base_settings.browser.pacing.min_delay_ms,
                self.base_settings.browser.pacing.max_delay_ms,
            ),
            "stable": (1500, 2500),
        }
        minimum, maximum = speed_ranges[preferences.execution_speed]
        browser = replace(
            self.base_settings.browser,
            pacing=replace(
                self.base_settings.browser.pacing,
                min_delay_ms=minimum,
                max_delay_ms=maximum,
            ),
        )
        rights_statement = replace(
            self.base_settings.rights_statement,
            no_result_confirm_ms=preferences.no_result_confirm_seconds * 1000,
            preview_download_delay_ms=preferences.preview_download_delay_ms,
            download_timeout_ms=preferences.download_timeout_seconds * 1000,
        )
        profile_id = preferences.ai_model_profile or self.base_settings.ai.profile_id.value
        profile = next(
            (
                item
                for item in self.base_settings.ai_models
                if item.profile_id.value == profile_id
            ),
            self.base_settings.ai,
        )
        reasoning_mode = (
            preferences.ai_reasoning_mode
            if preferences.ai_reasoning_mode in profile.reasoning_modes
            else profile.default_reasoning_mode
        )
        selected = select_ai_model(
            self.base_settings,
            profile.profile_id.value,
            reasoning_mode=reasoning_mode,
        )
        credentials = selected.rights_credentials
        if rights_account is not None:
            profile_root = self.runtime_root / "web-browser-profiles" / (
                f"jshrss-{rights_account.id}"
            )
            browser = replace(
                browser,
                user_data_dir=profile_root,
                storage_state_path=profile_root / "session-state.json",
            )
            credentials = replace(
                credentials,
                credit_code=rights_account.account,
                mobile=rights_account.secondary_account,
                password=rights_account.password,
            )
        erp = selected.erp
        if erp_account is not None:
            erp_profile_root = self.runtime_root / "web-browser-profiles" / (
                f"erp-{erp_account.id}"
            )
            erp = replace(erp, user_data_dir=erp_profile_root)
        return replace(
            selected,
            browser=browser,
            erp=erp,
            rights_statement=rights_statement,
            rights_credentials=credentials,
        )
