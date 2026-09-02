from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from ehrm.browser.access_token import AccessTokenManager
from ehrm.modules.nocobase.auth_client import NocoBaseAuthClient
from ehrm.modules.nocobase.exceptions import (
    NocoBaseAuthenticationError,
    NocoBaseInvalidTokenError,
)
from ehrm.modules.nocobase.jwt_token import decode_jwt_claims
from ehrm.modules.nocobase.models import (
    NocoBaseCredentials,
    NocoBaseLoginResult,
    NocoBaseTokenClaims,
)


_Result = TypeVar("_Result")


class NocoBaseAuthSession:
    """Keeps a JWT in memory and refreshes it once when necessary."""

    def __init__(
        self,
        auth_client: NocoBaseAuthClient,
        credentials: NocoBaseCredentials,
        logger: logging.Logger,
        token_manager: AccessTokenManager | None = None,
    ) -> None:
        self._auth_client = auth_client
        self._credentials = credentials
        self._logger = logger
        self._token_manager = token_manager
        self._login: NocoBaseLoginResult | None = None
        self._token: str | None = None
        self._claims: NocoBaseTokenClaims | None = None

    @property
    def login(self) -> NocoBaseLoginResult | None:
        return self._login

    @property
    def claims(self) -> NocoBaseTokenClaims | None:
        return self._claims

    def invalidate(self) -> None:
        self._login = None
        self._token = None
        self._claims = None
        if self._token_manager is not None:
            self._token_manager.invalidate()

    def authorization_token(self) -> str:
        if self._token is None:
            self._restore_token()
        if self._token is not None and self._claims is not None:
            if not self._claims.is_expired():
                return self._token
            self._logger.info("NocoBase 本地 Token 已到期")
            self.invalidate()

        self._logger.info("NocoBase 有效 Token 不存在，正在登录")
        self._login = self._auth_client.sign_in(self._credentials)
        self._token = self._login.token
        self._claims = self._login.claims
        if self._token_manager is not None:
            self._token_manager.save_token(self._token)
        return self._token

    def _restore_token(self) -> None:
        if self._token_manager is None:
            return
        persisted = self._token_manager.get_token()
        if not persisted:
            return
        try:
            claims = decode_jwt_claims(persisted)
        except NocoBaseAuthenticationError:
            self._logger.warning("NocoBase 本地 Token 无法解析，已清除")
            self._token_manager.invalidate()
            return
        if claims.is_expired():
            self._logger.info("NocoBase 本地 Token 已到期，已清除")
            self._token_manager.invalidate()
            return
        self._token = persisted
        self._claims = claims
        self._logger.info(
            "NocoBase 已恢复未过期 Token user_id=%s expires_at=%s",
            claims.user_id,
            claims.expires_at,
        )

    def execute(
        self,
        operation: Callable[[str], _Result],
        *,
        operation_name: str,
    ) -> _Result:
        token = self.authorization_token()
        try:
            return operation(token)
        except NocoBaseInvalidTokenError:
            self._logger.info(
                "NocoBase 接口拒绝 Token，重新登录后重试 operation=%s",
                operation_name,
            )
            self.invalidate()
            refreshed = self.authorization_token()
            return operation(refreshed)
