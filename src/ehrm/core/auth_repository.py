from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import sqlite3
import time
from typing import Any


LOCAL_OWNER_ID = "local-desktop"


def normalize_nocobase_api_key(value: str) -> str:
    """Validate a bare API key without exposing its contents in errors."""
    key = value.strip()
    if not key or key == "******":
        raise ValueError("请输入 NocoBase API 密钥")
    if any(character.isspace() for character in key):
        raise ValueError("NocoBase API 密钥不能包含空白字符，请只粘贴密钥，不包含 Bearer 前缀")
    return key


class SystemType(str, Enum):
    NOCOBASE = "NOCOBASE"
    JSHRSS = "JSHRSS"
    MEDICAL = "MEDICAL"
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
    is_enabled: bool = True
    api_key: str = field(default="", repr=False)
    credential_id: int | None = None

    @property
    def profile(self) -> dict[str, Any]:
        try:
            value = json.loads(self.profile_json)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}


def medical_browser_profile_name(account: SystemAccount) -> str:
    """Rotate browser state when medical credentials change."""
    generation = account.profile.get("session_generation", 0)
    if not isinstance(generation, int) or generation < 0:
        generation = 0
    return f"medical-{account.id}-v{generation}"


def social_browser_profile_name(account: SystemAccount) -> str:
    """Retain the old social profile until shared credentials are rotated."""
    generation = account.profile.get("session_generation", 0)
    if not isinstance(generation, int) or generation < 1:
        return f"jshrss-{account.id}"
    return f"jshrss-{account.id}-v{generation}"


@dataclass(frozen=True, slots=True)
class AuthenticationSession:
    account_id: int
    session_data: str
    expires_at: int | None
    last_verified_at: int | None
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class GovernmentIdentity:
    id: int
    owner_id: str
    account: str
    password: str = field(repr=False)
    display_name: str = ""


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
                    api_key TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    is_default INTEGER NOT NULL DEFAULT 0,
                    is_enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    CHECK(system_type IN ('NOCOBASE', 'JSHRSS', 'MEDICAL', 'ERP')),
                    CHECK(is_default IN (0, 1)),
                    CHECK(is_enabled IN (0, 1)),
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

                CREATE TABLE IF NOT EXISTS government_identities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    account TEXT NOT NULL,
                    password TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    disambiguator TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(owner_id, account, disambiguator)
                );

                """
            )
            # Foreign keys must be disabled before the migration transaction:
            # rebuilding system_accounts must not cascade-delete auth_sessions.
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(system_accounts)")}
            if "api_key" not in columns:
                connection.execute("ALTER TABLE system_accounts ADD COLUMN api_key TEXT NOT NULL DEFAULT ''")
            table_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'system_accounts'"
            ).fetchone()["sql"]
            if "'MEDICAL'" not in table_sql:
                connection.execute(
                    """
                    CREATE TABLE system_accounts_medical_migration (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        owner_id TEXT NOT NULL,
                        system_type TEXT NOT NULL,
                        account TEXT NOT NULL,
                        secondary_account TEXT NOT NULL DEFAULT '',
                        password TEXT NOT NULL,
                        api_key TEXT NOT NULL DEFAULT '',
                        display_name TEXT NOT NULL DEFAULT '',
                        profile_json TEXT NOT NULL DEFAULT '{}',
                        is_default INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        CHECK(system_type IN ('NOCOBASE', 'JSHRSS', 'MEDICAL', 'ERP')),
                        CHECK(is_default IN (0, 1)),
                        UNIQUE(owner_id, system_type, account, secondary_account)
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO system_accounts_medical_migration
                    SELECT id, owner_id, system_type, account, secondary_account,
                           password, api_key, display_name, profile_json,
                           is_default, created_at, updated_at
                    FROM system_accounts
                    """
                )
                connection.execute("DROP TABLE system_accounts")
                connection.execute(
                    "ALTER TABLE system_accounts_medical_migration RENAME TO system_accounts"
                )
                connection.execute(
                    """CREATE UNIQUE INDEX idx_system_accounts_default
                    ON system_accounts(owner_id, system_type)
                    WHERE is_default = 1"""
                )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(system_accounts)")}
            if "credential_id" not in columns:
                connection.execute("ALTER TABLE system_accounts ADD COLUMN credential_id INTEGER")
            if "is_enabled" not in columns:
                connection.execute("ALTER TABLE system_accounts ADD COLUMN is_enabled INTEGER NOT NULL DEFAULT 1")
            self._link_legacy_government_accounts(connection)
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("账号数据库迁移后外键校验失败")
            connection.execute("PRAGMA user_version = 5")
        try:
            self.database_path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _link_legacy_government_accounts(connection: sqlite3.Connection) -> None:
        """Attach old portal records without changing their IDs or browser sessions."""
        rows = connection.execute(
            """SELECT * FROM system_accounts
               WHERE credential_id IS NULL AND system_type IN ('JSHRSS', 'MEDICAL')
               ORDER BY id"""
        ).fetchall()
        for row in rows:
            try:
                profile = json.loads(row["profile_json"])
            except (TypeError, ValueError):
                profile = {}
            if row["system_type"] != "MEDICAL" and (
                not isinstance(profile, dict) or profile.get("login_method") != "government_sso"
            ):
                continue
            identity = connection.execute(
                """SELECT id FROM government_identities
                   WHERE owner_id = ? AND account = ? AND password = ? ORDER BY id LIMIT 1""",
                (row["owner_id"], row["account"], row["password"]),
            ).fetchone()
            if identity is None:
                same_login = connection.execute(
                    """SELECT 1 FROM government_identities
                       WHERE owner_id = ? AND account = ? LIMIT 1""",
                    (row["owner_id"], row["account"]),
                ).fetchone()
                cursor = connection.execute(
                    """INSERT INTO government_identities
                       (owner_id, account, password, display_name, disambiguator, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["owner_id"], row["account"], row["password"], row["display_name"],
                        f"legacy-{row['id']}" if same_login else "",
                        row["created_at"], row["updated_at"],
                    ),
                )
                identity_id = int(cursor.lastrowid)
            else:
                identity_id = int(identity["id"])
            connection.execute(
                "UPDATE system_accounts SET credential_id = ? WHERE id = ?",
                (identity_id, row["id"]),
            )

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
                    is_enabled = 1,
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

    def save_nocobase_api_key(
        self,
        api_key: str = "",
        *,
        display_name: str = "",
        account_id: int | None = None,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> SystemAccount:
        """Save or rotate a key; blank input preserves an already configured key.

        Explicit configuration replaces only this connection's password/session.
        The independent field and fixed repr mask prevent treating credentials as keys.
        """
        now = int(time.time())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if account_id is None:
                row = connection.execute(
                    """SELECT * FROM system_accounts WHERE owner_id = ? AND system_type = ?
                       ORDER BY is_default DESC, updated_at DESC, id LIMIT 1""",
                    (owner_id, SystemType.NOCOBASE.value),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM system_accounts WHERE id = ? AND owner_id = ? AND system_type = ?",
                    (account_id, owner_id, SystemType.NOCOBASE.value),
                ).fetchone()
                if row is None:
                    raise ValueError("NocoBase 连接不存在，请刷新后重试")
            key = normalize_nocobase_api_key(api_key) if api_key.strip() else (str(row["api_key"]) if row else "")
            if not key:
                raise ValueError("请先配置 NocoBase API 密钥；旧账号密码不能作为 API 密钥使用")
            name = display_name.strip() or (str(row["display_name"]) if row else "") or "NocoBase"
            connection.execute(
                "UPDATE system_accounts SET is_default = 0 WHERE owner_id = ? AND system_type = ?",
                (owner_id, SystemType.NOCOBASE.value),
            )
            if row is None:
                cursor = connection.execute(
                    """INSERT INTO system_accounts
                       (owner_id, system_type, account, password, api_key, display_name,
                        profile_json, is_default, created_at, updated_at)
                       VALUES (?, 'NOCOBASE', 'api-key', '', ?, ?, ?, 1, ?, ?)""",
                    (owner_id, key, name, '{"auth_type":"api_key"}', now, now),
                )
                saved_id = int(cursor.lastrowid)
            else:
                saved_id = int(row["id"])
                # 保留连接 ID 和非敏感关联信息，切换后不再保留该连接的登录密码。
                profile = self._account(row).profile
                profile["auth_type"] = "api_key"
                connection.execute(
                    """UPDATE system_accounts SET password = '', api_key = ?, display_name = ?,
                       profile_json = ?, is_default = 1, updated_at = ? WHERE id = ?""",
                    (key, name, json.dumps(profile, ensure_ascii=False), now, saved_id),
                )
                connection.execute("DELETE FROM auth_sessions WHERE account_id = ?", (saved_id,))
        saved = self.get_account_by_id(saved_id, owner_id=owner_id)
        assert saved is not None
        return saved

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
                WHERE owner_id = ? AND system_type = ? AND is_default = 1 AND is_enabled = 1
                LIMIT 1
                """,
                (owner_id, system_type.value),
            ).fetchone()
        return self._account(row) if row is not None else None

    def get_account_by_id(
        self,
        account_id: int,
        *,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> SystemAccount | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM system_accounts WHERE id = ? AND owner_id = ?",
                (account_id, owner_id),
            ).fetchone()
        return self._account(row) if row is not None else None

    def list_accounts(
        self,
        system_type: SystemType | None = None,
        *,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> tuple[SystemAccount, ...]:
        query = "SELECT * FROM system_accounts WHERE owner_id = ? AND is_enabled = 1"
        parameters: list[object] = [owner_id]
        if system_type is not None:
            query += " AND system_type = ?"
            parameters.append(system_type.value)
        query += " ORDER BY system_type, is_default DESC, updated_at DESC, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._account(row) for row in rows)

    def set_default_account(
        self,
        system_type: SystemType,
        account_id: int,
        *,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> SystemAccount:
        now = int(time.time())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM system_accounts WHERE id = ? AND owner_id = ? AND system_type = ? AND is_enabled = 1",
                (account_id, owner_id, system_type.value),
            ).fetchone()
            if row is None:
                raise ValueError("所选账号不存在或不属于该系统")
            connection.execute(
                "UPDATE system_accounts SET is_default = 0 WHERE owner_id = ? AND system_type = ?",
                (owner_id, system_type.value),
            )
            connection.execute(
                "UPDATE system_accounts SET is_default = 1, updated_at = ? WHERE id = ?",
                (now, account_id),
            )
        result = self.get_account_by_id(account_id, owner_id=owner_id)
        assert result is not None
        return result

    def list_government_identities(
        self, *, owner_id: str = LOCAL_OWNER_ID
    ) -> tuple[GovernmentIdentity, ...]:
        with self._connect() as connection:
            # Desktop and Web share this database; include accounts created by an
            # older process after this repository instance was initialized.
            connection.execute("BEGIN IMMEDIATE")
            self._link_legacy_government_accounts(connection)
            rows = connection.execute(
                """SELECT id, owner_id, account, password, display_name
                   FROM government_identities WHERE owner_id = ? ORDER BY id""",
                (owner_id,),
            ).fetchall()
        return tuple(self._government_identity(row) for row in rows)

    def get_government_identity(
        self, identity_id: int, *, owner_id: str = LOCAL_OWNER_ID
    ) -> GovernmentIdentity | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id, owner_id, account, password, display_name
                   FROM government_identities WHERE id = ? AND owner_id = ?""",
                (identity_id, owner_id),
            ).fetchone()
        return self._government_identity(row) if row is not None else None

    def government_bindings(
        self, identity_id: int, *, owner_id: str = LOCAL_OWNER_ID
    ) -> tuple[SystemAccount, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM system_accounts
                   WHERE owner_id = ? AND credential_id = ? AND is_enabled = 1 ORDER BY id""",
                (owner_id, identity_id),
            ).fetchall()
        return tuple(self._account(row) for row in rows)

    def save_government_identity(
        self,
        account: str,
        password: str = "",
        *,
        display_name: str = "",
        identity_id: int | None = None,
        social_enabled: bool | None = None,
        medical_enabled: bool | None = None,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> GovernmentIdentity:
        normalized = account.strip()
        if not normalized:
            raise ValueError("政务网登录账号不能为空")
        now = int(time.time())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if identity_id is None:
                if not password:
                    raise ValueError("请填写政务网登录密码")
                if connection.execute(
                    """SELECT 1 FROM government_identities
                       WHERE owner_id = ? AND account = ? LIMIT 1""",
                    (owner_id, normalized),
                ).fetchone():
                    raise ValueError("该政务网登录账号已存在，请编辑原账号")
                try:
                    cursor = connection.execute(
                        """INSERT INTO government_identities
                           (owner_id, account, password, display_name, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (owner_id, normalized, password, display_name.strip(), now, now),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError("该政务网登录账号已存在，请编辑原账号") from exc
                saved_id = int(cursor.lastrowid)
            else:
                current = connection.execute(
                    """SELECT * FROM government_identities WHERE id = ? AND owner_id = ?""",
                    (identity_id, owner_id),
                ).fetchone()
                if current is None:
                    raise ValueError("政务网账号不存在，请刷新后重试")
                if normalized != current["account"] and not password:
                    raise ValueError("更换政务网登录名时请同时填写新密码")
                if normalized != current["account"] and connection.execute(
                    """SELECT 1 FROM government_identities
                       WHERE owner_id = ? AND account = ? AND id != ? LIMIT 1""",
                    (owner_id, normalized, identity_id),
                ).fetchone():
                    raise ValueError("该政务网登录账号已存在，请编辑原账号")
                resolved_password = password or str(current["password"])
                resolved_name = display_name.strip() or str(current["display_name"])
                credentials_changed = normalized != current["account"] or resolved_password != current["password"]
                try:
                    connection.execute(
                        """UPDATE government_identities
                           SET account = ?, password = ?, display_name = ?, disambiguator = ?, updated_at = ?
                           WHERE id = ?""",
                        (
                            normalized, resolved_password, resolved_name,
                            "" if normalized != current["account"] else current["disambiguator"],
                            now, identity_id,
                        ),
                    )
                    bound_rows = connection.execute(
                        "SELECT * FROM system_accounts WHERE owner_id = ? AND credential_id = ?",
                        (owner_id, identity_id),
                    ).fetchall()
                    for bound in bound_rows:
                        profile = self._account(bound).profile
                        if credentials_changed:
                            generation = profile.get("session_generation", 0)
                            profile["session_generation"] = (
                                generation if isinstance(generation, int) and generation >= 0 else 0
                            ) + 1
                        connection.execute(
                            """UPDATE system_accounts
                               SET account = ?, password = ?, display_name = ?, profile_json = ?, updated_at = ?
                               WHERE id = ?""",
                            (
                                normalized, resolved_password, resolved_name,
                                json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
                                now, bound["id"],
                            ),
                        )
                        if credentials_changed:
                            connection.execute("DELETE FROM auth_sessions WHERE account_id = ?", (bound["id"],))
                except sqlite3.IntegrityError as exc:
                    raise ValueError("登录账号与已有账号冲突，请先核对社保和医保绑定") from exc
                saved_id = identity_id
            for system_type, enabled in (
                (SystemType.JSHRSS, social_enabled),
                (SystemType.MEDICAL, medical_enabled),
            ):
                if enabled is not None:
                    self._set_government_purpose(connection, saved_id, system_type, enabled, now, owner_id)
        saved = self.get_government_identity(saved_id, owner_id=owner_id)
        assert saved is not None
        return saved

    def bind_government_identity(
        self,
        identity_id: int,
        system_type: SystemType,
        *,
        owner_id: str = LOCAL_OWNER_ID,
    ) -> SystemAccount:
        if system_type not in {SystemType.JSHRSS, SystemType.MEDICAL}:
            raise ValueError("政务网账号只能绑定社保或医保")
        now = int(time.time())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            bound_id = self._set_government_purpose(connection, identity_id, system_type, True, now, owner_id)
        bound = self.get_account_by_id(bound_id, owner_id=owner_id)
        assert bound is not None
        return bound

    @staticmethod
    def _set_government_purpose(
        connection: sqlite3.Connection,
        identity_id: int,
        system_type: SystemType,
        enabled: bool,
        now: int,
        owner_id: str,
    ) -> int:
        identity = connection.execute(
            "SELECT * FROM government_identities WHERE id = ? AND owner_id = ?",
            (identity_id, owner_id),
        ).fetchone()
        if identity is None:
            raise ValueError("政务网账号不存在，请刷新后重试")
        existing = connection.execute(
            """SELECT * FROM system_accounts
               WHERE owner_id = ? AND system_type = ? AND credential_id = ? LIMIT 1""",
            (owner_id, system_type.value, identity_id),
        ).fetchone()
        if not enabled:
            if existing is not None and existing["is_enabled"]:
                profile = AuthenticationRepository._account(existing).profile
                generation = profile.get("session_generation", 0)
                profile["session_generation"] = (generation if isinstance(generation, int) and generation >= 0 else 0) + 1
                connection.execute(
                    """UPDATE system_accounts SET is_enabled = 0, is_default = 0,
                       profile_json = ?, updated_at = ? WHERE id = ?""",
                    (json.dumps(profile, ensure_ascii=False, separators=(",", ":")), now, existing["id"]),
                )
                connection.execute("DELETE FROM auth_sessions WHERE account_id = ?", (existing["id"],))
            return int(existing["id"]) if existing is not None else 0
        if existing is not None and existing["is_enabled"]:
            return int(existing["id"])
        has_default = connection.execute(
            """SELECT 1 FROM system_accounts
               WHERE owner_id = ? AND system_type = ? AND is_default = 1 AND is_enabled = 1""",
            (owner_id, system_type.value),
        ).fetchone()
        if existing is not None:
            connection.execute(
                """UPDATE system_accounts SET is_enabled = 1, is_default = ?, updated_at = ? WHERE id = ?""",
                (int(has_default is None), now, existing["id"]),
            )
            return int(existing["id"])
        conflict = connection.execute(
            """SELECT 1 FROM system_accounts
               WHERE owner_id = ? AND system_type = ? AND account = ? AND secondary_account = ''""",
            (owner_id, system_type.value, identity["account"]),
        ).fetchone()
        if conflict:
            raise ValueError("该账号已用于此业务，请检查现有绑定")
        cursor = connection.execute(
            """INSERT INTO system_accounts
               (owner_id, system_type, account, secondary_account, password,
                display_name, profile_json, is_default, created_at, updated_at, credential_id)
               VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)""",
            (
                owner_id, system_type.value, identity["account"], identity["password"],
                identity["display_name"], '{"login_method":"government_sso","session_generation":0}',
                int(has_default is None), now, now, identity_id,
            ),
        )
        return int(cursor.lastrowid)

    def link_legacy_government_account(self, account_id: int) -> SystemAccount:
        """Keep the old account API compatible with the unified identity store."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM system_accounts WHERE id = ?", (account_id,)).fetchone()
            if row is None:
                raise ValueError("账号不存在")
            if row["credential_id"] is None:
                self._link_legacy_government_accounts(connection)
        saved = self.get_account_by_id(account_id, owner_id=str(row["owner_id"]))
        assert saved is not None
        return saved

    def update_account_by_id(
        self,
        system_type: SystemType,
        account_id: int,
        *,
        account: str,
        password: str,
        display_name: str,
        profile: dict[str, Any],
        owner_id: str = LOCAL_OWNER_ID,
    ) -> SystemAccount:
        normalized_account = account.strip()
        if not normalized_account or not password:
            raise ValueError("登录账号和密码不能为空")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT account, password FROM system_accounts WHERE id = ? AND owner_id = ? AND system_type = ?",
                (account_id, owner_id, system_type.value),
            ).fetchone()
            if current is None:
                raise ValueError("所选账号不存在或不属于该系统")
            try:
                connection.execute(
                    """UPDATE system_accounts
                    SET account = ?, password = ?, display_name = ?, profile_json = ?,
                        updated_at = ?
                    WHERE id = ?""",
                    (
                        normalized_account, password, display_name.strip(),
                        json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
                        int(time.time()), account_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("该医保登录账号已存在") from exc
            if current["account"] != normalized_account or current["password"] != password:
                connection.execute(
                    "DELETE FROM auth_sessions WHERE account_id = ?", (account_id,)
                )
        updated = self.get_account_by_id(account_id, owner_id=owner_id)
        assert updated is not None
        return updated

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
            is_enabled=bool(row["is_enabled"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            api_key=str(row["api_key"]),
            credential_id=int(row["credential_id"]) if row["credential_id"] is not None else None,
        )

    @staticmethod
    def _government_identity(row: sqlite3.Row) -> GovernmentIdentity:
        return GovernmentIdentity(
            id=int(row["id"]), owner_id=str(row["owner_id"]),
            account=str(row["account"]), password=str(row["password"]),
            display_name=str(row["display_name"]),
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
