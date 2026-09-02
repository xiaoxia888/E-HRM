from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class NocoBaseCredentials:
    account: str
    password: str

    def __post_init__(self) -> None:
        if not self.account.strip():
            raise ValueError("NocoBase 登录账号不能为空")
        if not self.password:
            raise ValueError("NocoBase 登录密码不能为空")

    def to_payload(self) -> dict[str, str]:
        return {
            "account": self.account.strip(),
            "password": self.password,
        }


@dataclass(frozen=True, slots=True)
class NocoBaseUser:
    user_id: int
    username: str
    nickname: str
    erp_user_id: str | None


@dataclass(frozen=True, slots=True)
class NocoBaseTokenClaims:
    user_id: int
    temporary: bool
    issued_at: int
    expires_at: int

    @property
    def expires_at_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.expires_at, tz=timezone.utc)

    def is_expired(
        self,
        *,
        now_timestamp: float | None = None,
        leeway_seconds: int = 30,
    ) -> bool:
        current = (
            datetime.now(tz=timezone.utc).timestamp()
            if now_timestamp is None
            else now_timestamp
        )
        return current + max(0, leeway_seconds) >= self.expires_at


@dataclass(frozen=True, slots=True, repr=False)
class NocoBaseLoginResult:
    user: NocoBaseUser
    token: str
    claims: NocoBaseTokenClaims

    def __repr__(self) -> str:
        return (
            "NocoBaseLoginResult("
            f"user={self.user!r}, token='<已脱敏>', claims={self.claims!r})"
        )

    def is_expired(self, *, now_timestamp: float | None = None) -> bool:
        return self.claims.is_expired(now_timestamp=now_timestamp)
