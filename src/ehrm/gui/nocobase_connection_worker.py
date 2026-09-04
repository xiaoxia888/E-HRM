from __future__ import annotations

import logging
from threading import Event

from playwright.sync_api import sync_playwright
from PySide6.QtCore import QThread, Signal

from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.nocobase import NocoBaseAuthClient, NocoBaseCredentials
from ehrm.modules.nocobase.token_store import create_nocobase_token_manager


class NocoBaseConnectionWorker(QThread):
    """Authenticates NocoBase and persists the verified JWT off the UI thread."""

    status_changed = Signal(str)
    succeeded = Signal()
    failed = Signal(str, str)

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        credentials: NocoBaseCredentials,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._credentials = credentials
        self._cancel_requested = Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        try:
            if self._cancel_requested.is_set():
                return
            self.status_changed.emit("正在调用 NocoBase 登录接口…")
            with sync_playwright() as playwright:
                request = playwright.request.new_context()
                try:
                    result = NocoBaseAuthClient(
                        self._settings.nocobase,
                        request,
                        self._logger,
                    ).sign_in(self._credentials)
                finally:
                    request.dispose()
            if self._cancel_requested.is_set():
                return

            repository = AuthenticationRepository(
                self._settings.auth_database_path
            )
            repository.save_account(
                SystemType.NOCOBASE,
                self._credentials.account,
                self._credentials.password,
                display_name=result.user.nickname or result.user.username,
                profile={
                    "id": result.user.user_id,
                    "username": result.user.username,
                    "nickname": result.user.nickname,
                    "erp_userId": result.user.erp_user_id,
                },
            )
            token_manager = create_nocobase_token_manager(
                self._settings.auth_database_path,
                self._credentials.account,
                password=self._credentials.password,
            )
            token_manager.save_token(result.token)
            token_manager.mark_verified()
            self.succeeded.emit()
        except EhrmError as exc:
            summary = display_message(exc.code, exc.message)
            details = exc.message if exc.message != summary else (exc.details or "")
            self.failed.emit(summary, details)
        except Exception as exc:
            self._logger.exception("NocoBase 连接测试发生未知错误")
            self.failed.emit("NocoBase 连接测试失败", str(exc))
