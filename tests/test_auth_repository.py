import json
from pathlib import Path
import sqlite3
import pytest

from ehrm.core.auth_repository import (
    AuthenticationRepository,
    SystemType,
    social_browser_profile_name,
)


def test_accounts_are_isolated_by_owner_system_and_account(tmp_path: Path) -> None:
    repository = AuthenticationRepository(tmp_path / "data" / "auth.sqlite3")
    first = repository.save_account(
        SystemType.NOCOBASE,
        "account-1",
        "password-1",
        owner_id="web-user-1",
    )
    second = repository.save_account(
        SystemType.NOCOBASE,
        "account-2",
        "password-2",
        owner_id="web-user-1",
    )
    other_owner = repository.save_account(
        SystemType.NOCOBASE,
        "account-1",
        "password-3",
        owner_id="web-user-2",
    )

    assert len({first.id, second.id, other_owner.id}) == 3
    assert repository.get_default_account(
        SystemType.NOCOBASE, owner_id="web-user-1"
    ) == second
    assert repository.get_default_account(
        SystemType.NOCOBASE, owner_id="web-user-2"
    ) == other_owner
    assert [
        item.account
        for item in repository.list_accounts(
            SystemType.NOCOBASE,
            owner_id="web-user-1",
        )
    ] == ["account-2", "account-1"]


def test_session_can_be_cleared_without_deleting_credentials(tmp_path: Path) -> None:
    repository = AuthenticationRepository(tmp_path / "auth.sqlite3")
    account = repository.save_account(
        SystemType.JSHRSS,
        "unit-code",
        "password",
        secondary_account="mobile",
    )
    repository.save_session(account.id, "access-token", verified=True)

    assert repository.get_session(account.id) is not None
    repository.delete_session(account.id)

    assert repository.get_session(account.id) is None
    restored = repository.get_account(
        SystemType.JSHRSS,
        "unit-code",
        secondary_account="mobile",
    )
    assert restored is not None
    assert restored.password == "password"


def test_erp_storage_state_is_stored_as_plain_json(tmp_path: Path) -> None:
    repository = AuthenticationRepository(tmp_path / "auth.sqlite3")
    account = repository.save_account(SystemType.ERP, "erp-user", "erp-password")
    state = {
        "cookies": [
            {
                "name": "NCC_TOKEN",
                "value": "token-value",
                "domain": "erp.example.test",
                "path": "/",
            }
        ],
        "origins": [],
    }
    repository.save_session(account.id, json.dumps(state), verified=True)

    restored = repository.get_session(account.id)
    assert restored is not None
    assert json.loads(restored.session_data) == state


def test_deleting_account_cascades_to_session(tmp_path: Path) -> None:
    repository = AuthenticationRepository(tmp_path / "auth.sqlite3")
    account = repository.save_account(SystemType.ERP, "erp-user", "password")
    repository.save_session(account.id, "{}")

    repository.delete_account(SystemType.ERP, "erp-user")

    assert repository.get_session(account.id) is None


def test_medical_accounts_and_default_are_separate_from_social_security(tmp_path: Path) -> None:
    repository = AuthenticationRepository(tmp_path / "auth.sqlite3")
    social = repository.save_account(
        SystemType.JSHRSS, "same-user", "social-password",
        profile={"login_method": "government_sso"},
    )
    first = repository.save_account(
        SystemType.MEDICAL, "same-user", "medical-password",
        profile={"login_method": "government_sso"},
    )
    second = repository.save_account(
        SystemType.MEDICAL, "other-user", "other-password",
        profile={"login_method": "government_sso"},
    )
    assert social.id != first.id
    assert repository.get_default_account(SystemType.MEDICAL) == second
    repository.set_default_account(SystemType.MEDICAL, first.id)
    assert repository.get_default_account(SystemType.MEDICAL) == first
    assert repository.get_default_account(SystemType.JSHRSS) == social


def test_legacy_account_database_migrates_without_losing_sessions(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE system_accounts (
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
            CREATE TABLE auth_sessions (
                account_id INTEGER PRIMARY KEY,
                session_data TEXT NOT NULL,
                expires_at INTEGER,
                last_verified_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(account_id) REFERENCES system_accounts(id) ON DELETE CASCADE
            );
            INSERT INTO system_accounts VALUES (
                7, 'local-desktop', 'JSHRSS', 'old-user', '', 'old-password',
                '旧社保账号', '{"login_method":"government_sso"}', 1, 1, 1
            );
            INSERT INTO auth_sessions VALUES (7, 'old-session', NULL, NULL, 1, 1);
            """
        )
    repository = AuthenticationRepository(path)
    old = repository.get_account_by_id(7)
    assert old is not None and old.account == "old-user"
    assert repository.get_session(7).session_data == "old-session"  # type: ignore[union-attr]
    medical = repository.save_account(
        SystemType.MEDICAL, "medical-user", "medical-password",
        profile={"login_method": "government_sso"},
    )
    assert medical.system_type is SystemType.MEDICAL
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_government_migration_merges_only_identical_credentials_and_preserves_sessions(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    repository = AuthenticationRepository(path)
    social = repository.save_account(
        SystemType.JSHRSS, "same-login", "same-password",
        profile={"login_method": "government_sso"},
    )
    medical = repository.save_account(
        SystemType.MEDICAL, "same-login", "same-password",
        profile={"login_method": "government_sso"},
    )
    different = repository.save_account(
        SystemType.MEDICAL, "other-login", "other-password",
        profile={"login_method": "government_sso"}, make_default=False,
    )
    repository.save_session(social.id, "social-session")
    repository.save_session(medical.id, "medical-session")

    migrated = AuthenticationRepository(path)
    identities = migrated.list_government_identities()
    assert len(identities) == 2
    assert migrated.get_account_by_id(social.id).credential_id == migrated.get_account_by_id(medical.id).credential_id  # type: ignore[union-attr]
    assert migrated.get_account_by_id(different.id).credential_id != migrated.get_account_by_id(social.id).credential_id  # type: ignore[union-attr]
    assert migrated.get_session(social.id).session_data == "social-session"  # type: ignore[union-attr]
    assert migrated.get_session(medical.id).session_data == "medical-session"  # type: ignore[union-attr]
    assert len(AuthenticationRepository(path).list_government_identities()) == 2


def test_one_government_identity_binds_both_portals_and_rotates_only_its_sessions(tmp_path: Path) -> None:
    repository = AuthenticationRepository(tmp_path / "auth.sqlite3")
    identity = repository.save_government_identity("user-a", "password-a", display_name="八化建")
    social = repository.bind_government_identity(identity.id, SystemType.JSHRSS)
    medical = repository.bind_government_identity(identity.id, SystemType.MEDICAL)
    assert social.id != medical.id
    assert social_browser_profile_name(social) == f"jshrss-{social.id}"
    assert repository.bind_government_identity(identity.id, SystemType.MEDICAL).id == medical.id
    repository.save_session(social.id, "social-session")
    repository.save_session(medical.id, "medical-session")
    other = repository.save_account(SystemType.ERP, "erp", "erp-password")
    repository.save_session(other.id, "erp-session")

    updated = repository.save_government_identity(
        "user-a", "password-b", identity_id=identity.id, display_name="八化建"
    )
    assert updated.id == identity.id
    assert repository.get_account_by_id(social.id).password == "password-b"  # type: ignore[union-attr]
    assert repository.get_account_by_id(medical.id).password == "password-b"  # type: ignore[union-attr]
    assert repository.get_account_by_id(social.id).profile["session_generation"] == 1  # type: ignore[union-attr]
    assert social_browser_profile_name(repository.get_account_by_id(social.id)) == f"jshrss-{social.id}-v1"  # type: ignore[arg-type]
    assert repository.get_account_by_id(medical.id).profile["session_generation"] == 1  # type: ignore[union-attr]
    assert repository.get_session(social.id) is None
    assert repository.get_session(medical.id) is None
    assert repository.get_session(other.id).session_data == "erp-session"  # type: ignore[union-attr]


def test_changing_government_login_requires_new_password(tmp_path: Path) -> None:
    repository = AuthenticationRepository(tmp_path / "auth.sqlite3")
    identity = repository.save_government_identity("old", "password")
    try:
        repository.save_government_identity("new", identity_id=identity.id)
    except ValueError as exc:
        assert "新密码" in str(exc)
    else:
        raise AssertionError("更换登录名时应要求提供密码")


def test_government_platform_selection_hides_disabled_account_and_keeps_id(tmp_path: Path) -> None:
    repository = AuthenticationRepository(tmp_path / "auth.sqlite3")
    identity = repository.save_government_identity(
        "gov-user", "password", display_name="南化建",
        social_enabled=True, medical_enabled=True,
    )
    medical = next(account for account in repository.government_bindings(identity.id)
                   if account.system_type is SystemType.MEDICAL)
    social = next(account for account in repository.government_bindings(identity.id)
                  if account.system_type is SystemType.JSHRSS)
    repository.save_session(social.id, "social-session")
    repository.save_session(medical.id, "medical-session")

    repository.save_government_identity(
        "gov-user", identity_id=identity.id,
        social_enabled=False, medical_enabled=True,
    )
    assert repository.government_bindings(identity.id) == (medical,)
    assert not any(account.id == social.id for account in repository.list_accounts(SystemType.JSHRSS))
    assert repository.get_default_account(SystemType.JSHRSS) is None
    assert repository.get_session(social.id) is None
    assert repository.get_session(medical.id) is not None
    assert repository.get_account_by_id(social.id).is_enabled is False  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="不存在"):
        repository.set_default_account(SystemType.JSHRSS, social.id)

    repository.save_government_identity("gov-user", identity_id=identity.id, social_enabled=True)
    social_again = next(account for account in repository.list_accounts(SystemType.JSHRSS)
                        if account.credential_id == identity.id)
    assert social_again.id == social.id
    assert social_again.profile["session_generation"] == 1
    assert repository.get_default_account(SystemType.JSHRSS).id == social.id  # type: ignore[union-attr]


def test_government_platform_selection_rolls_back_on_conflicting_business_account(tmp_path: Path) -> None:
    repository = AuthenticationRepository(tmp_path / "auth.sqlite3")
    repository.save_account(SystemType.JSHRSS, "gov-user", "direct-password", make_default=True)
    with pytest.raises(ValueError, match="已用于此业务"):
        repository.save_government_identity(
            "gov-user", "password", display_name="南化建",
            social_enabled=True, medical_enabled=True,
        )
    assert repository.list_government_identities() == ()
    assert repository.list_accounts(SystemType.MEDICAL) == ()
