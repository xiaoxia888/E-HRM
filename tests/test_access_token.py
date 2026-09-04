from pathlib import Path

from ehrm.browser.access_token import (
    AccessTokenManager,
    MemoryAccessTokenStore,
    create_rights_access_token_manager,
)
from ehrm.core.auth_repository import AuthenticationRepository, SystemType


def test_access_token_manager_persists_token_by_account_id() -> None:
    store = MemoryAccessTokenStore()
    account_key = "42"
    manager = AccessTokenManager(account_key, store)

    manager.save_token("test-secret-token")

    restored = AccessTokenManager(account_key, store)
    assert restored.get_token() == "test-secret-token"


def test_access_token_manager_invalidates_memory_and_persistent_store() -> None:
    store = MemoryAccessTokenStore()
    manager = AccessTokenManager("test-account", store)
    manager.save_token("test-secret-token")

    manager.invalidate()

    assert manager.get_token() is None
    assert AccessTokenManager("test-account", store).get_token() is None


def test_manager_reloads_token_saved_by_another_manager_after_empty_cache() -> None:
    store = MemoryAccessTokenStore()
    waiting_manager = AccessTokenManager("test-account", store)
    login_manager = AccessTokenManager("test-account", store)

    assert waiting_manager.get_token() is None
    login_manager.save_token("new-access-token")

    assert waiting_manager.get_token() == "new-access-token"


def test_rights_manager_does_not_create_account_until_token_is_saved(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "auth.sqlite3"
    manager = create_rights_access_token_manager(
        database_path,
        "new-credit-code",
        "new-mobile",
        password="verified-password",
    )
    repository = AuthenticationRepository(database_path)

    assert manager.get_token() is None
    assert repository.get_default_account(SystemType.JSHRSS) is None

    manager.save_token("verified-access-token")

    account = repository.get_default_account(SystemType.JSHRSS)
    assert account is not None
    assert account.account == "new-credit-code"
    assert account.secondary_account == "new-mobile"
    assert account.password == "verified-password"
    assert repository.get_session(account.id).session_data == "verified-access-token"
