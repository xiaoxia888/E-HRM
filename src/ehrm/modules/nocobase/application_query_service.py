from __future__ import annotations

import logging

from playwright.sync_api import sync_playwright

from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.settings import AppSettings
from ehrm.modules.nocobase.auth_client import NocoBaseAuthClient
from ehrm.modules.nocobase.auth_session import NocoBaseAuthSession
from ehrm.modules.nocobase.models import (
    NocoBaseCredentials,
    NocoBaseRightsApplicationDetail,
    NocoBaseRightsApplicationPage,
)
from ehrm.modules.nocobase.rights_application_client import (
    NocoBaseRightsApplicationClient,
)
from ehrm.modules.nocobase.token_store import create_nocobase_token_manager


class NocoBaseApplicationQueryService:
    """UI-neutral NocoBase query service shared by desktop and web adapters."""

    def __init__(self, settings: AppSettings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger

    def list_applications(
        self,
        *,
        page: int,
        page_size: int,
    ) -> NocoBaseRightsApplicationPage:
        return self._execute(
            lambda session, client: session.execute(
                lambda token: client.list_applications(
                    token,
                    page=page,
                    page_size=page_size,
                ),
                operation_name="权益申请分页查询",
            )
        )

    def get_application(
        self,
        application_id: int,
    ) -> NocoBaseRightsApplicationDetail:
        return self._execute(
            lambda session, client: session.execute(
                lambda token: client.get_application(token, application_id),
                operation_name="权益申请详情查询",
            )
        )

    def _execute(self, operation):
        account = AuthenticationRepository(
            self._settings.auth_database_path
        ).get_default_account(SystemType.NOCOBASE)
        if account is None or not account.account or not account.password:
            raise ValueError("请先在系统设置中保存完整的 NocoBase 账号和密码")
        credentials = NocoBaseCredentials(account.account, account.password)
        token_manager = create_nocobase_token_manager(
            self._settings.auth_database_path,
            account.account,
            password=account.password,
        )
        with sync_playwright() as playwright:
            request = playwright.request.new_context()
            try:
                session = NocoBaseAuthSession(
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
                return operation(session, client)
            finally:
                request.dispose()
