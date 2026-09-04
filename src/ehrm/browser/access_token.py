from __future__ import annotations

from threading import RLock
from typing import Protocol

from pathlib import Path

from ehrm.core.auth_repository import (
    AuthenticationRepository,
    LOCAL_OWNER_ID,
    SystemAccount,
    SystemType,
)


class AccessTokenStore(Protocol):
    """Persistent secret storage used by the shared token manager."""

    def save_token(self, account_key: str, token: str) -> None: ...

    def load_token(self, account_key: str) -> str | None: ...

    def delete_token(self, account_key: str) -> None: ...


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


class RightsAccountSessionStore:
    """Defers JSHRSS account creation until a login returns a real token."""

    def __init__(
        self,
        repository: AuthenticationRepository,
        credit_code: str,
        mobile: str,
        password: str,
        owner_id: str,
    ) -> None:
        self.repository = repository
        self.credit_code = credit_code
        self.mobile = mobile
        self.password = password
        self.owner_id = owner_id

    def _account(self) -> SystemAccount | None:
        return self.repository.get_account(
            SystemType.JSHRSS,
            self.credit_code,
            secondary_account=self.mobile,
            owner_id=self.owner_id,
        )

    def save_token(self, account_key: str, token: str) -> None:
        del account_key
        account = self._account()
        if account is None or (self.password and self.password != account.password):
            account = self.repository.save_account(
                SystemType.JSHRSS,
                self.credit_code,
                self.password,
                secondary_account=self.mobile,
                owner_id=self.owner_id,
            )
        self.repository.save_session(account.id, token)

    def load_token(self, account_key: str) -> str | None:
        del account_key
        account = self._account()
        if account is None:
            return None
        session = self.repository.get_session(account.id)
        return session.session_data if session is not None else None

    def delete_token(self, account_key: str) -> None:
        del account_key
        account = self._account()
        if account is not None:
            self.repository.delete_session(account.id)

    def mark_verified(self) -> None:
        account = self._account()
        if account is not None:
            self.repository.mark_session_verified(account.id)


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
        if store is None:
            raise ValueError("Access-Token 存储未配置")
        self._store = store
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

    def mark_verified(self) -> None:
        marker = getattr(self._store, "mark_verified", None)
        if callable(marker):
            marker()


def create_rights_access_token_manager(
    database_path: Path,
    credit_code: str,
    mobile: str,
    *,
    password: str = "",
    owner_id: str = LOCAL_OWNER_ID,
) -> AccessTokenManager:
    """Builds a JSHRSS token manager backed by the unified SQLite database."""
    normalized_credit = credit_code.strip()
    normalized_mobile = mobile.strip()
    if not normalized_credit or not normalized_mobile:
        raise ValueError("智慧人社账号信息不完整")
    repository = AuthenticationRepository(database_path)
    return AccessTokenManager(
        f"{normalized_credit}|{normalized_mobile}",
        RightsAccountSessionStore(
            repository,
            normalized_credit,
            normalized_mobile,
            password,
            owner_id,
        ),
    )
