from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import sqlite3
import time
from typing import Any


LOCAL_OWNER_ID = "local-desktop"


class SystemType(str, Enum):
    NOCOBASE = "NOCOBASE"
    JSHRSS = "JSHRSS"
    ERP = "ERP"


@dataclass(frozen=True, slots=True)
class SystemAccount:
    id: int
    owner_id: str
    system_type: SystemType
    account: str
    secondary_account: str
    password: str
    display_name: str
    profile_json: str
    is_default: bool
    created_at: int
    updated_at: int

    @property
    def profile(self) -> dict[str, Any]:
        try:
            value = json.loads(self.profile_json)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}


@dataclass(frozen=True, slots=True)
class AuthenticationSession:
    account_id: int
    session_data: str
    expires_at: int | None
    last_verified_at: int | None
    created_at: int
    updated_at: int


class AuthenticationRepository:
    """SQLite persistence for external accounts and authentication sessions."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().resolve()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS system_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    system_type TEXT NOT NULL,
                    account TEXT NOT NULL,
                    secondary_account TEXT NOT NULL DEFAULT '',
                    password TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    CHECK(system_type IN ('NOCOBASE', 'JSHRSS', 'ERP')),
                    CHECK(is_default IN (0, 1)),
                    UNIQUE(owner_id, system_type, account, secondary_account)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_system_accounts_default
                ON system_accounts(owner_id, system_type)
                WHERE is_default = 1;

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    account_id INTEGER PRIMARY KEY,
                    session_data TEXT NOT NULL,
                    expires_at INTEGER,
                    last_verified_at INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(account_id)
                        REFERENCES system_accounts(id)
                        ON DELETE CASCADE
                );

                PRAGMA user_version = 1;
                """
            )
        try:
            self.database_path.chmod(0o600)
        except OSError:
            pass

    def save_account(
        self,
        system_type: SystemType,
        account: str,
        password: str,
        *,
        secondary_account: str = "",
        owner_id: str = LOCAL_OWNER_ID,
        display_name: str = "",
        profile: dict[str, Any] | None = None,
        make_default: bool = True,
    ) -> SystemAccount:
        normalized_account = account.strip()
        normalized_secondary = secondary_account.strip()
        if not normalized_account:
            raise ValueError("登录账号不能为空")
        now = int(time.time())
        profile_json = json.dumps(
            profile or {}, ensure_ascii=False, separators=(",", ":")
        )
        with self._connect() as connection:
            if make_default:
                connection.execute(
                    """
                    UPDATE system_accounts SET is_default = 0, updated_at = ?
                    WHERE owner_id = ? AND system_type = ?
                    """,
                    (now, owner_id, system_type.value),
                )
            connection.execute(
                """
                INSERT INTO system_accounts (
                    owner_id, system_type, account, secondary_account,
                    password, display_name, profile_json, is_default,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_id, system_type, account, secondary_account)
                DO UPDATE SET
                    password = excluded.password,
                    display_name = excluded.display_name,
                    profile_json = excluded.profile_json,
                    is_default = excluded.is_default,
                    updated_at = excluded.updated_at
                """,
                (
                    owner_id,
                    system_type.value,
                    normalized_account,
                    normalized_secondary,
                    password,
                    display_name.strip(),
                    profile_json,
                    int(make_default),
                    now,
                    now,
                ),
            )
        saved = self.get_account(
            system_type,
            normalized_account,
            secondary_account=normalized_secondary,
            owner_id=owner_id,
        )
        assert saved is not None
        return saved

    def get_account(
        self,
        system_type: SystemType,
        account: str,
        *,
        secondary_account: str = "",
        owner_id: str = LOCAL_OWNER_ID,
    ) -> SystemAccount | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM system_accounts
                WHERE owner_id = ? AND system_type = ?
                  AND account = ? AND secondary_account = ?
                """,
                (
                    owner_id,
                    system_type.value,
                    account.strip(),
                    secondary_account.strip(),
                ),
            ).fetchone()
        return self._account(row) if row is not None else None

    def get_default_account(
        self,
        system_type: SystemType,
        *,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> SystemAccount | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM system_accounts
                WHERE owner_id = ? AND system_type = ? AND is_default = 1
                LIMIT 1
                """,
                (owner_id, system_type.value),
            ).fetchone()
        return self._account(row) if row is not None else None

    def list_accounts(
        self,
        system_type: SystemType | None = None,
        *,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> tuple[SystemAccount, ...]:
        query = "SELECT * FROM system_accounts WHERE owner_id = ?"
        parameters: list[object] = [owner_id]
        if system_type is not None:
            query += " AND system_type = ?"
            parameters.append(system_type.value)
        query += " ORDER BY system_type, is_default DESC, updated_at DESC, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._account(row) for row in rows)

    def delete_account(
        self,
        system_type: SystemType,
        account: str,
        *,
        secondary_account: str = "",
        owner_id: str = LOCAL_OWNER_ID,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM system_accounts
                WHERE owner_id = ? AND system_type = ?
                  AND account = ? AND secondary_account = ?
                """,
                (
                    owner_id,
                    system_type.value,
                    account.strip(),
                    secondary_account.strip(),
                ),
            )

    def save_session(
        self,
        account_id: int,
        session_data: str,
        *,
        expires_at: int | None = None,
        verified: bool = False,
    ) -> None:
        normalized = session_data.strip()
        if not normalized:
            raise ValueError("登录会话不能为空")
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions (
                    account_id, session_data, expires_at, last_verified_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    session_data = excluded.session_data,
                    expires_at = excluded.expires_at,
                    last_verified_at = excluded.last_verified_at,
                    updated_at = excluded.updated_at
                """,
                (
                    account_id,
                    normalized,
                    expires_at,
                    now if verified else None,
                    now,
                    now,
                ),
            )

    def get_session(self, account_id: int) -> AuthenticationSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_sessions WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        if row is None:
            return None
        return AuthenticationSession(
            account_id=int(row["account_id"]),
            session_data=str(row["session_data"]),
            expires_at=(
                int(row["expires_at"])
                if row["expires_at"] is not None
                else None
            ),
            last_verified_at=(
                int(row["last_verified_at"])
                if row["last_verified_at"] is not None
                else None
            ),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    def mark_session_verified(self, account_id: int) -> None:
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE auth_sessions
                SET last_verified_at = ?, updated_at = ?
                WHERE account_id = ?
                """,
                (now, now, account_id),
            )

    def delete_session(self, account_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE account_id = ?",
                (account_id,),
            )

    @staticmethod
    def _account(row: sqlite3.Row) -> SystemAccount:
        return SystemAccount(
            id=int(row["id"]),
            owner_id=str(row["owner_id"]),
            system_type=SystemType(str(row["system_type"])),
            account=str(row["account"]),
            secondary_account=str(row["secondary_account"]),
            password=str(row["password"]),
            display_name=str(row["display_name"]),
            profile_json=str(row["profile_json"]),
            is_default=bool(row["is_default"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )


class RepositorySessionStore:
    """Adapts one account's SQLite session to AccessTokenManager's protocol."""

    def __init__(
        self,
        repository: AuthenticationRepository,
        account_id: int,
        *,
        expires_at_resolver: Any | None = None,
    ) -> None:
        self.repository = repository
        self.account_id = account_id
        self.expires_at_resolver = expires_at_resolver

    def save_token(self, account_key: str, token: str) -> None:
        del account_key
        expires_at = (
            self.expires_at_resolver(token)
            if self.expires_at_resolver is not None
            else None
        )
        self.repository.save_session(
            self.account_id,
            token,
            expires_at=expires_at,
        )

    def load_token(self, account_key: str) -> str | None:
        del account_key
        session = self.repository.get_session(self.account_id)
        return session.session_data if session is not None else None

    def delete_token(self, account_key: str) -> None:
        del account_key
        self.repository.delete_session(self.account_id)

    def mark_verified(self) -> None:
        self.repository.mark_session_verified(self.account_id)
