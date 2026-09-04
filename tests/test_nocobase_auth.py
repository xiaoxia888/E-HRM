import base64
import json
import logging
from pathlib import Path

import pytest

from ehrm.core.settings import load_settings
from ehrm.browser.access_token import AccessTokenManager, MemoryAccessTokenStore
from ehrm.modules.nocobase.auth_client import NocoBaseAuthClient
from ehrm.modules.nocobase.auth_session import NocoBaseAuthSession
from ehrm.modules.nocobase.exceptions import (
    NocoBaseAuthenticationError,
    NocoBaseInvalidTokenError,
)
from ehrm.modules.nocobase.jwt_token import decode_jwt_claims
from ehrm.modules.nocobase.models import NocoBaseCredentials
from ehrm.modules.nocobase.response import raise_for_nocobase_errors
from ehrm.modules.nocobase.token_store import create_nocobase_token_manager


def _jwt(*, user_id: int = 25, issued_at: int = 1_788_336_046, expires_at: int = 4_102_444_800) -> str:
    def encode(payload: dict[str, object]) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return ".".join(
        (
            encode({"alg": "HS256", "typ": "JWT"}),
            encode(
                {
                    "userId": user_id,
                    "temp": True,
                    "iat": issued_at,
                    "exp": expires_at,
                }
            ),
            "test-signature",
        )
    )


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self._payload = payload
        self.status = status
        self.disposed = False

    def json(self) -> object:
        return self._payload

    def dispose(self) -> None:
        self.disposed = True


class FakeRequest:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.response


def _login_payload(token: str | None = None) -> dict[str, object]:
    return {
        "data": {
            "user": {
                "id": 25,
                "username": "xiaguoxi",
                "nickname": "夏国玺",
                "erp_userId": "test-erp-user-id",
            },
            "token": token or _jwt(),
        }
    }


def test_auth_client_posts_configured_login_and_parses_jwt(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    response = FakeResponse(_login_payload())
    request = FakeRequest(response)
    client = NocoBaseAuthClient(
        settings.nocobase,
        request,  # type: ignore[arg-type]
        logging.getLogger("test.nocobase"),
    )

    result = client.sign_in(NocoBaseCredentials("xiaguoxi", "secret"))

    assert result.user.user_id == 25
    assert result.user.nickname == "夏国玺"
    assert result.claims.user_id == 25
    assert result.claims.temporary is True
    assert result.claims.expires_at == 4_102_444_800
    assert result.is_expired() is False
    assert "test-signature" not in repr(result)
    url, call = request.calls[0]
    assert url == settings.nocobase.base_url + settings.nocobase.sign_in_path
    assert call["data"] == {"account": "xiaguoxi", "password": "secret"}
    assert call["timeout"] == settings.nocobase.request_timeout_ms
    assert response.disposed is True


def test_decode_jwt_rejects_missing_expiry() -> None:
    payload = base64.urlsafe_b64encode(b'{"userId":25,"iat":1}').decode().rstrip("=")
    with pytest.raises(NocoBaseAuthenticationError, match="时间信息"):
        decode_jwt_claims(f"header.{payload}.signature")


def test_invalid_token_error_is_classified_for_reauthentication() -> None:
    with pytest.raises(NocoBaseInvalidTokenError, match="session has expired"):
        raise_for_nocobase_errors(
            {
                "errors": [
                    {
                        "message": "Your session has expired. Please sign in again.",
                        "code": "INVALID_TOKEN",
                    }
                ]
            }
        )


def test_auth_session_reauthenticates_and_retries_once_on_invalid_token() -> None:
    class FakeAuthClient:
        def __init__(self) -> None:
            self.calls = 0

        def sign_in(self, credentials: NocoBaseCredentials):
            self.calls += 1
            token = _jwt(expires_at=4_102_444_800 + self.calls)
            response = FakeResponse(_login_payload(token))
            request = FakeRequest(response)
            return NocoBaseAuthClient(
                load_settings(Path("config/settings.toml")).nocobase,
                request,  # type: ignore[arg-type]
                logging.getLogger("test.nocobase-session-login"),
            ).sign_in(credentials)

    auth_client = FakeAuthClient()
    session = NocoBaseAuthSession(
        auth_client,  # type: ignore[arg-type]
        NocoBaseCredentials("xiaguoxi", "secret"),
        logging.getLogger("test.nocobase-session"),
    )
    operation_tokens: list[str] = []

    def operation(token: str) -> str:
        operation_tokens.append(token)
        if len(operation_tokens) == 1:
            raise NocoBaseInvalidTokenError("expired")
        return "success"

    result = session.execute(operation, operation_name="分页查询")

    assert result == "success"
    assert auth_client.calls == 2
    assert len(operation_tokens) == 2
    assert operation_tokens[0] != operation_tokens[1]


def test_auth_session_restores_unexpired_token_without_login() -> None:
    class UnexpectedAuthClient:
        def sign_in(self, credentials: NocoBaseCredentials):
            raise AssertionError("未过期的持久化 Token 不应重新登录")

    store = MemoryAccessTokenStore()
    manager = AccessTokenManager("nocobase-account", store)
    token = _jwt()
    manager.save_token(token)
    restored_manager = AccessTokenManager("nocobase-account", store)
    session = NocoBaseAuthSession(
        UnexpectedAuthClient(),  # type: ignore[arg-type]
        NocoBaseCredentials("xiaguoxi", "secret"),
        logging.getLogger("test.nocobase-session-restore"),
        restored_manager,
    )

    assert session.authorization_token() == token
    assert session.claims is not None
    assert session.claims.user_id == 25


def test_auth_session_clears_expired_token_and_logs_in_again() -> None:
    class FakeAuthClient:
        calls = 0

        def sign_in(self, credentials: NocoBaseCredentials):
            self.calls += 1
            response = FakeResponse(_login_payload(_jwt()))
            return NocoBaseAuthClient(
                load_settings(Path("config/settings.toml")).nocobase,
                FakeRequest(response),  # type: ignore[arg-type]
                logging.getLogger("test.nocobase-expired-login"),
            ).sign_in(credentials)

    store = MemoryAccessTokenStore()
    manager = AccessTokenManager("nocobase-account", store)
    manager.save_token(_jwt(issued_at=1, expires_at=2))
    auth_client = FakeAuthClient()
    session = NocoBaseAuthSession(
        auth_client,  # type: ignore[arg-type]
        NocoBaseCredentials("xiaguoxi", "secret"),
        logging.getLogger("test.nocobase-expired-session"),
        AccessTokenManager("nocobase-account", store),
    )

    assert session.authorization_token() == _jwt()
    assert auth_client.calls == 1
    assert AccessTokenManager("nocobase-account", store).get_token() == _jwt()


def test_nocobase_token_manager_persists_separate_accounts(
    tmp_path: Path,
) -> None:
    database = tmp_path / "auth.sqlite3"
    first = create_nocobase_token_manager(database, "account-1", password="p1")
    second = create_nocobase_token_manager(database, "account-2", password="p2")
    first.save_token(_jwt(user_id=1))
    second.save_token(_jwt(user_id=2))

    assert create_nocobase_token_manager(database, "account-1").get_token() == _jwt(
        user_id=1
    )
    assert create_nocobase_token_manager(database, "account-2").get_token() == _jwt(
        user_id=2
    )
