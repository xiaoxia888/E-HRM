from __future__ import annotations

import logging
from urllib.parse import urlsplit

from playwright.sync_api import APIRequestContext, APIResponse
from playwright.sync_api import Error as PlaywrightError

from ehrm.core.settings import NocoBaseSettings
from ehrm.modules.nocobase.exceptions import (
    NocoBaseAuthenticationError,
    NocoBaseRequestError,
)
from ehrm.modules.nocobase.jwt_token import decode_jwt_claims
from ehrm.modules.nocobase.models import (
    NocoBaseCredentials,
    NocoBaseLoginResult,
    NocoBaseUser,
)
from ehrm.modules.nocobase.response import raise_for_nocobase_errors


class NocoBaseAuthClient:
    """Authenticates against NocoBase without browser page automation."""

    def __init__(
        self,
        settings: NocoBaseSettings,
        request: APIRequestContext,
        logger: logging.Logger,
    ) -> None:
        self.settings = settings
        self.request = request
        self.logger = logger

    def sign_in(self, credentials: NocoBaseCredentials) -> NocoBaseLoginResult:
        url = self._url(self.settings.sign_in_path)
        try:
            response = self.request.post(
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                data=credentials.to_payload(),
                timeout=self.settings.request_timeout_ms,
            )
        except PlaywrightError as exc:
            raise NocoBaseAuthenticationError(
                "NocoBase 登录接口请求失败",
                details=str(exc),
            ) from exc
        result = self._parse_login_response(response)
        self.logger.info(
            "NocoBase 登录成功 user_id=%s username=%s expires_at=%s",
            result.user.user_id,
            result.user.username,
            result.claims.expires_at,
        )
        return result

    def _parse_login_response(
        self,
        response: APIResponse,
    ) -> NocoBaseLoginResult:
        try:
            try:
                payload: object = response.json()
            except Exception as exc:
                raise NocoBaseAuthenticationError(
                    "NocoBase 登录接口返回了无法解析的数据",
                    details=type(exc).__name__,
                ) from exc
            raise_for_nocobase_errors(payload)
            if not 200 <= response.status < 300:
                raise NocoBaseAuthenticationError(
                    f"NocoBase 登录接口返回 HTTP {response.status}"
                )
            if not isinstance(payload, dict):
                raise NocoBaseAuthenticationError("NocoBase 登录响应结构错误")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise NocoBaseAuthenticationError("NocoBase 登录响应缺少 data")
            raw_user = data.get("user")
            token = str(data.get("token") or "").strip()
            if not isinstance(raw_user, dict):
                raise NocoBaseAuthenticationError("NocoBase 登录响应缺少用户信息")
            if not token:
                raise NocoBaseAuthenticationError("NocoBase 登录响应缺少 Token")
            user = self._user(raw_user)
            claims = decode_jwt_claims(token)
            if claims.user_id != user.user_id:
                raise NocoBaseAuthenticationError(
                    "NocoBase Token 用户与登录用户不一致"
                )
            if claims.is_expired():
                raise NocoBaseAuthenticationError(
                    "NocoBase 登录接口返回了已过期的 Token"
                )
            return NocoBaseLoginResult(user=user, token=token, claims=claims)
        except NocoBaseRequestError as exc:
            raise NocoBaseAuthenticationError(exc.message) from exc
        finally:
            response.dispose()

    @staticmethod
    def _user(payload: dict[str, object]) -> NocoBaseUser:
        user_id = payload.get("id")
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            raise NocoBaseAuthenticationError("NocoBase 登录用户缺少有效 id")
        return NocoBaseUser(
            user_id=user_id,
            username=str(payload.get("username") or "").strip(),
            nickname=str(payload.get("nickname") or "").strip(),
            erp_user_id=(
                str(payload.get("erp_userId")).strip()
                if payload.get("erp_userId") is not None
                else None
            ),
        )

    def _url(self, path: str) -> str:
        parsed = urlsplit(self.settings.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise NocoBaseAuthenticationError("NocoBase 服务地址配置错误")
        return f"{self.settings.base_url.rstrip('/')}/{path.lstrip('/')}"
