from __future__ import annotations

from pathlib import Path

from ehrm.core.auth_repository import (
    AuthenticationRepository,
    LOCAL_OWNER_ID,
    SystemAccount,
    SystemType,
)


class ErpCredentialStore:
    """Stores ERP accounts and passwords in the application SQLite database."""

    def __init__(
        self,
        database_path: Path,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> None:
        self.repository = AuthenticationRepository(database_path)
        self.owner_id = owner_id

    def default_account(self) -> SystemAccount | None:
        return self.repository.get_default_account(
            SystemType.ERP,
            owner_id=self.owner_id,
        )

    def load_password(self, username: str) -> str | None:
        if not username.strip():
            return None
        account = self.repository.get_account(
            SystemType.ERP,
            username,
            owner_id=self.owner_id,
        )
        return account.password if account is not None else None

    def save_password(self, username: str, password: str) -> None:
        self.repository.save_account(
            SystemType.ERP,
            username,
            password,
            owner_id=self.owner_id,
        )

    def delete_password(self, username: str) -> None:
        self.repository.delete_account(
            SystemType.ERP,
            username,
            owner_id=self.owner_id,
        )


class RightsCredentialStore:
    """Stores Jiangsu HRSS unit credentials in the SQLite account table."""

    def __init__(
        self,
        database_path: Path,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> None:
        self.repository = AuthenticationRepository(database_path)
        self.owner_id = owner_id

    def default_account(self) -> SystemAccount | None:
        return self.repository.get_default_account(
            SystemType.JSHRSS,
            owner_id=self.owner_id,
        )

    def load_password(self, account_key: str) -> str | None:
        credit_code, mobile = self._parse_key(account_key)
        if not credit_code or not mobile:
            return None
        account = self.repository.get_account(
            SystemType.JSHRSS,
            credit_code,
            secondary_account=mobile,
            owner_id=self.owner_id,
        )
        return account.password if account is not None else None

    def save_password(self, account_key: str, password: str) -> None:
        credit_code, mobile = self._parse_key(account_key)
        if not credit_code or not mobile:
            raise ValueError("智慧人社账号信息不完整")
        self.repository.save_account(
            SystemType.JSHRSS,
            credit_code,
            password,
            secondary_account=mobile,
            owner_id=self.owner_id,
        )

    def delete_password(self, account_key: str) -> None:
        credit_code, mobile = self._parse_key(account_key)
        if not credit_code or not mobile:
            return
        self.repository.delete_account(
            SystemType.JSHRSS,
            credit_code,
            secondary_account=mobile,
            owner_id=self.owner_id,
        )

    @staticmethod
    def _parse_key(account_key: str) -> tuple[str, str]:
        credit_code, separator, mobile = account_key.partition("|")
        if not separator:
            return "", ""
        return credit_code.strip(), mobile.strip()
