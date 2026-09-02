from __future__ import annotations

from hashlib import sha256
from threading import RLock
from typing import Protocol
from urllib.parse import urlsplit

from ehrm.modules.erp.credential_store import SystemCredentialStore


class AccessTokenStore(Protocol):
    """Persistent secret storage used by the shared token manager."""

    def save_token(self, account_key: str, token: str) -> None: ...

    def load_token(self, account_key: str) -> str | None: ...

    def delete_token(self, account_key: str) -> None: ...


class SystemAccessTokenStore:
    """Stores the upstream bearer token in the operating-system vault."""

    def __init__(self) -> None:
        self._credentials = SystemCredentialStore(
            "NJNCC.EHRM.JSHRSS.ACCESS_TOKEN",
            "江苏智慧人社 Access-Token",
        )

    def save_token(self, account_key: str, token: str) -> None:
        self._credentials.save_password(account_key, token)

    def load_token(self, account_key: str) -> str | None:
        return self._credentials.load_password(account_key)

    def delete_token(self, account_key: str) -> None:
        self._credentials.delete_password(account_key)


class MemoryAccessTokenStore:
    """Small deterministic store for tests and non-persistent runtimes."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def save_token(self, account_key: str, token: str) -> None:
        self._tokens[account_key] = token

    def load_token(self, account_key: str) -> str | None:
        return self._tokens.get(account_key)

    def delete_token(self, account_key: str) -> None:
        self._tokens.pop(account_key, None)


class AccessTokenManager:
    """Keeps one token in memory and optionally restores it from a vault."""

    def __init__(
        self,
        account_key: str,
        store: AccessTokenStore | None = None,
    ) -> None:
        normalized_key = account_key.strip()
        if not normalized_key:
            raise ValueError("Access-Token 账号标识不能为空")
        self.account_key = normalized_key
        self._store = store or SystemAccessTokenStore()
        self._token: str | None = None
        self._loaded = False
        self._lock = RLock()

    def get_token(self) -> str | None:
        with self._lock:
            # A separate login/test worker may refresh this account's token.
            # Do not cache an empty vault result forever.
            if not self._loaded or self._token is None:
                persisted = self._store.load_token(self.account_key)
                self._token = persisted.strip() if persisted else None
                self._loaded = True
            return self._token

    def save_token(self, token: str) -> None:
        normalized = token.strip()
        if not normalized:
            raise ValueError("Access-Token 不能为空")
        with self._lock:
            self._store.save_token(self.account_key, normalized)
            self._token = normalized
            self._loaded = True

    def invalidate(self) -> None:
        with self._lock:
            self._store.delete_token(self.account_key)
            self._token = None
            self._loaded = True


def build_access_token_account_key(
    login_url: str,
    credit_code: str | None,
    mobile: str | None,
) -> str:
    """Builds a stable non-PII key for one host and unit account."""
    parsed = urlsplit(login_url)
    host = parsed.netloc.casefold().strip()
    if not host:
        raise ValueError("登录地址缺少主机，无法生成 Access-Token 账号标识")
    identity = "|".join(
        (
            (credit_code or "").strip().casefold(),
            (mobile or "").strip().casefold(),
        )
    )
    digest = sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"{host}:{digest}"
