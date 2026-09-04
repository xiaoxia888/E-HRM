from __future__ import annotations

import logging

from playwright.sync_api import sync_playwright
from PySide6.QtCore import QThread, Signal

from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.nocobase import (
    NocoBaseAuthClient,
    NocoBaseAuthSession,
    NocoBaseCredentials,
    NocoBaseRightsApplicationClient,
    create_nocobase_token_manager,
)


class NocoBaseApplicationDetailWorker(QThread):
    """Loads one NocoBase rights application without blocking QML."""

    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        application_id: int,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._application_id = application_id

    def run(self) -> None:
        try:
            repository = AuthenticationRepository(
                self._settings.auth_database_path
            )
            account = repository.get_default_account(SystemType.NOCOBASE)
            if account is None or not account.account or not account.password:
                raise ValueError(
                    "请先在账号设置中保存完整的 NocoBase 账号和密码"
                )
            credentials = NocoBaseCredentials(account.account, account.password)
            token_manager = create_nocobase_token_manager(
                self._settings.auth_database_path,
                account.account,
                password=account.password,
            )
            with sync_playwright() as playwright:
                request = playwright.request.new_context()
                try:
                    auth_session = NocoBaseAuthSession(
                        NocoBaseAuthClient(
                            self._settings.nocobase,
                            request,
                            self._logger,
                        ),
                        credentials,
                        self._logger,
                        token_manager,
                    )
                    client = NocoBaseRightsApplicationClient(
                        self._settings.nocobase,
                        request,
                        self._logger,
                    )
                    result = auth_session.execute(
                        lambda token: client.get_application(
                            token,
                            self._application_id,
                        ),
                        operation_name="权益申请详情查询",
                    )
                finally:
                    request.dispose()
            self.succeeded.emit(result)
        except EhrmError as exc:
            self.failed.emit(
                display_message(exc.code, exc.message),
                exc.details or "",
            )
        except Exception as exc:
            self._logger.exception("NocoBase 权益申请详情查询发生未知错误")
            self.failed.emit("权益申请详情查询失败", str(exc))
