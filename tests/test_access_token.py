from pathlib import Path

from ehrm.browser.access_token import (
    AccessTokenManager,
    MemoryAccessTokenStore,
    build_access_token_account_key,
)
from ehrm.core.settings import load_settings


def test_access_token_manager_persists_without_exposing_token_in_key(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    store = MemoryAccessTokenStore()
    account_key = build_access_token_account_key(
        settings.site.login_url,
        "test-credit-code",
        "test-mobile",
    )
    manager = AccessTokenManager(account_key, store)

    manager.save_token("test-secret-token")

    restored = AccessTokenManager(account_key, store)
    assert restored.get_token() == "test-secret-token"
    assert "test-credit-code" not in account_key
    assert "test-mobile" not in account_key


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
