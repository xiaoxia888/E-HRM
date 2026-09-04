import json
from pathlib import Path

from ehrm.core.auth_repository import (
    AuthenticationRepository,
    SystemType,
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
