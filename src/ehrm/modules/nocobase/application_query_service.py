from __future__ import annotations

import logging

from playwright.sync_api import sync_playwright

from ehrm.core.auth_repository import (
    AuthenticationRepository,
    SystemType,
    normalize_nocobase_api_key,
)
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.nocobase.exceptions import (
    NocoBaseApiKeyInvalidError,
    NocoBaseInvalidTokenError,
    NocoBaseRequestError,
)
from ehrm.modules.nocobase.models import (
    NocoBaseRightsApplicationDetail,
    NocoBaseRightsApplicationPage,
)
from ehrm.modules.nocobase.rights_application_client import (
    NocoBaseRightsApplicationClient,
)


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
            lambda key, client: client.list_applications(key, page=page, page_size=page_size)
        )

    def get_application(
        self,
        application_id: int,
    ) -> NocoBaseRightsApplicationDetail:
        return self._execute(
            lambda key, client: client.get_application(key, application_id)
        )

    def test_connection(self, *, api_key: str = "", account_id: int | None = None) -> None:
        """Read one application to verify authentication and required read access.

        An unsaved key is used only for this request. No credentials or sessions
        are written; a successful empty list also confirms read access.
        """
        key = (
            normalize_nocobase_api_key(api_key)
            if api_key.strip()
            else self._configured_key(account_id)
        )
        self._execute(
            lambda token, client: client.list_applications(token, page=1, page_size=1),
            api_key=key,
        )

    def _configured_key(self, account_id: int | None = None) -> str:
        repository = AuthenticationRepository(self._settings.auth_database_path)
        account = (
            repository.get_account_by_id(account_id)
            if account_id is not None
            else repository.get_default_account(SystemType.NOCOBASE)
        )
        if account is None or account.system_type is not SystemType.NOCOBASE or not account.api_key:
            raise ValueError("请先在系统设置中配置 NocoBase API 密钥")
        return normalize_nocobase_api_key(account.api_key)

    def _execute(self, operation, *, api_key: str | None = None):
        key = api_key if api_key is not None else self._configured_key()
        with sync_playwright() as playwright:
            request = playwright.request.new_context()
            try:
                client = NocoBaseRightsApplicationClient(
                    self._settings.nocobase,
                    request,
                    self._logger,
                )
                return operation(key, client)
            except NocoBaseInvalidTokenError:
                # 长效密钥被撤销或失效时不自动登录，也不删除用户保存的配置。
                raise NocoBaseApiKeyInvalidError("NocoBase API 密钥无效或已失效，请在系统设置中更换密钥") from None
            except EhrmError as exc:
                # 上游错误可能回显请求信息；密钥不得进入页面、日志或异常链。
                details = exc.details.replace(key, "[已隐藏]") if exc.details else None
                raise type(exc)(exc.message.replace(key, "[已隐藏]"), details=details) from None
            except Exception as exc:
                # 未知的上游异常也不能携带请求中的密钥或授权头返回给用户。
                raise NocoBaseRequestError(
                    "NocoBase 查询失败，请检查服务地址和网络连接",
                    details=type(exc).__name__,
                ) from None
            finally:
                request.dispose()
