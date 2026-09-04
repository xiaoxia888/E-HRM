from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


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


class NocoBaseProblemType(str, Enum):
    SOCIAL_SECURITY_RIGHTS = "social_security_rights"


@dataclass(frozen=True, slots=True)
class NocoBaseRightsApplication:
    application_id: int
    code: str
    status: str
    title: str
    problem_type: str
    initiator_id: int | None
    initiator_name: str
    initiation_date: datetime | None
    estimate_time: float
    actual_time: float
    estimate_date: datetime | None
    actual_date: datetime | None


@dataclass(frozen=True, slots=True)
class NocoBasePageMeta:
    count: int
    page: int
    page_size: int
    total_page: int
    allowed_actions: dict[str, tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class NocoBaseRightsApplicationPage:
    records: tuple[NocoBaseRightsApplication, ...]
    meta: NocoBasePageMeta


@dataclass(frozen=True, slots=True)
class NocoBaseRelatedPerson:
    person_id: int
    status: str
    insurance_type: str
    start_month: datetime | None
    end_month: datetime | None
    identity_number: str
    department: str
    name: str
    company: str
    print_group: str = ""


@dataclass(frozen=True, slots=True)
class NocoBaseRightsApplicationDetail:
    application_id: int
    code: str
    status: str
    title: str
    problem_type: str
    created_at: datetime | None
    initiation_date: datetime | None
    estimate_time: float
    actual_time: float
    estimate_date: datetime | None
    actual_date: datetime | None
    created_by_name: str
    initiator_name: str
    problem_description: str
    handling_method: str
    related_persons: tuple[NocoBaseRelatedPerson, ...]
    attachment_names: tuple[str, ...]
    allowed_actions: dict[str, tuple[int, ...]]
