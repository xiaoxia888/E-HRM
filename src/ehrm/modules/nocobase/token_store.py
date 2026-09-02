from __future__ import annotations

from hashlib import sha256
from urllib.parse import urlsplit

from ehrm.modules.erp.credential_store import SystemCredentialStore


class NocoBaseSystemTokenStore:
    """Stores NocoBase JWTs in the operating-system credential vault."""

    def __init__(self) -> None:
        self._credentials = SystemCredentialStore(
            "NJNCC.EHRM.NOCOBASE.ACCESS_TOKEN",
            "NocoBase Authorization Token",
        )

    def save_token(self, account_key: str, token: str) -> None:
        self._credentials.save_password(account_key, token)

    def load_token(self, account_key: str) -> str | None:
        return self._credentials.load_password(account_key)

    def delete_token(self, account_key: str) -> None:
        self._credentials.delete_password(account_key)


def build_nocobase_token_account_key(base_url: str, account: str) -> str:
    """Builds a stable, non-plaintext key for one NocoBase account."""
    parsed = urlsplit(base_url)
    host = parsed.netloc.casefold().strip()
    normalized_account = account.casefold().strip()
    if not host:
        raise ValueError("NocoBase 服务地址缺少主机")
    if not normalized_account:
        raise ValueError("NocoBase 登录账号不能为空")
    digest = sha256(normalized_account.encode("utf-8")).hexdigest()[:24]
    return f"{host}:{digest}"
