from __future__ import annotations

from pathlib import Path

from ehrm.core.auth_repository import (
    AuthenticationRepository,
    LOCAL_OWNER_ID,
    SystemAccount,
    SystemType,
)


class NocoBaseCredentialStore:
    """Stores NocoBase accounts and passwords in the application database."""

    def __init__(
        self,
        database_path: Path,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> None:
        self.repository = AuthenticationRepository(database_path)
        self.owner_id = owner_id

    def default_account(self) -> SystemAccount | None:
        return self.repository.get_default_account(
            SystemType.NOCOBASE,
            owner_id=self.owner_id,
        )

    def load_password(self, account: str) -> str | None:
        if not account.strip():
            return None
        saved = self.repository.get_account(
            SystemType.NOCOBASE,
            account,
            owner_id=self.owner_id,
        )
        return saved.password if saved is not None else None

    def save_password(self, account: str, password: str) -> None:
        self.repository.save_account(
            SystemType.NOCOBASE,
            account,
            password,
            owner_id=self.owner_id,
        )

