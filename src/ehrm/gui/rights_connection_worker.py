from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from PySide6.QtCore import QThread, Signal

from ehrm.browser.access_token import AccessTokenManager, MemoryAccessTokenStore
from ehrm.browser.captcha_policy import is_allowed_host_url
from ehrm.browser.login import LoginService
from ehrm.browser.manager import BrowserManager
from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import AuthenticationFailedError, EhrmError
from ehrm.core.settings import AppSettings


class RightsConnectionWorker(QThread):
    """Tests saved rights credentials in an isolated browser profile."""

    status_changed = Signal(str)
    succeeded = Signal()
    failed = Signal(str, str)

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        credit_code: str,
        mobile: str,
        password: str,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._credit_code = credit_code
        self._mobile = mobile
        self._password = password
        self._cancel_requested = Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        try:
            self.status_changed.emit("正在启动隔离的登录验证环境…")
            with TemporaryDirectory(prefix="ehrm-rights-connection-") as directory:
                root = Path(directory)
                runtime_settings = replace(
                    self._settings,
                    browser=replace(
                        self._settings.browser,
                        user_data_dir=root / "browser-profile",
                        storage_state_path=root / "session-state.json",
                    ),
                    rights_credentials=replace(
                        self._settings.rights_credentials,
                        credit_code=self._credit_code,
                        mobile=self._mobile,
                        password=self._password,
                    ),
                )
                # A connection test must not persist unverified credentials.
                # Keep its token in memory until the complete login succeeds.
                access_tokens = AccessTokenManager(
                    "rights-connection-test",
                    MemoryAccessTokenStore(),
                )
                stealth_enabled = (
                    runtime_settings.captcha.stealth_enabled
                    and is_allowed_host_url(
                        runtime_settings.site.login_url,
                        runtime_settings.captcha.allowed_hosts,
                    )
                )
                with BrowserManager(
                    runtime_settings.browser,
                    stealth_enabled=stealth_enabled,
                ) as browser:
                    login = LoginService(
                        browser.page,
                        runtime_settings,
                        self._cancel_requested.is_set,
                        self.status_changed.emit,
                        access_tokens,
                    )
                    login.ensure_authenticated(
                        username=self._credit_code,
                        mobile=self._mobile,
                        password=self._password,
                    )
                    token = access_tokens.get_token()
                    if not token:
                        raise AuthenticationFailedError(
                            "登录完成但未获取 Access-Token"
                        )
                repository = AuthenticationRepository(
                    runtime_settings.auth_database_path
                )
                account = repository.save_account(
                    SystemType.JSHRSS,
                    self._credit_code,
                    self._password,
                    secondary_account=self._mobile,
                )
                repository.save_session(account.id, token, verified=True)
            self.succeeded.emit()
        except EhrmError as exc:
            summary = display_message(exc.code, exc.message)
            details = exc.message if exc.message != summary else (exc.details or "")
            self.failed.emit(summary, details)
        except Exception as exc:
            self._logger.exception("智慧人社连接测试发生未知错误")
            self.failed.emit("智慧人社连接测试失败", str(exc))
