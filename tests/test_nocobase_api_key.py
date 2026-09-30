from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import load_settings
from ehrm.modules.nocobase.application_query_service import NocoBaseApplicationQueryService
from ehrm.web.app import create_app
from ehrm.web.settings_service import WebSettingsService
from ehrm.web.tasks import TaskCoordinator


class _Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.payload = payload
        self.disposed = False

    def json(self) -> object:
        return self.payload

    def dispose(self) -> None:
        self.disposed = True


class _Request:
    """Only GET is supported: any password-login POST is an unexpected failure."""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []
        self.disposed = False

    def get(self, url: str, **kwargs) -> _Response:
        self.calls.append((url, kwargs))
        return self.response

    def dispose(self) -> None:
        self.disposed = True


def _transport(monkeypatch: pytest.MonkeyPatch, response: _Response) -> _Request:
    request = _Request(response)

    @contextmanager
    def fake_playwright():
        yield SimpleNamespace(request=SimpleNamespace(new_context=lambda **_kwargs: request))

    monkeypatch.setattr(
        "ehrm.modules.nocobase.application_query_service.sync_playwright", fake_playwright
    )
    return request


def _settings(tmp_path: Path):
    return load_settings(Path("config/settings.toml"), data_root=tmp_path)


def _save_key(settings, tmp_path: Path, key: str = "test-api-key"):
    return WebSettingsService(settings, tmp_path).save_account(
        SystemType.NOCOBASE, api_key=key, display_name="NocoBase 测试连接"
    )


def test_existing_database_gains_independent_api_key_field_without_converting_password(
    tmp_path: Path,
) -> None:
    database = tmp_path / "accounts.sqlite3"
    # A real pre-change database: migration must not infer a key from its password.
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE system_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT NOT NULL,
                system_type TEXT NOT NULL, account TEXT NOT NULL,
                secondary_account TEXT NOT NULL DEFAULT '', password TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '', profile_json TEXT NOT NULL DEFAULT '{}',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                UNIQUE(owner_id, system_type, account, secondary_account)
            )"""
        )
        connection.execute(
            """INSERT INTO system_accounts
               (owner_id, system_type, account, password, is_default, created_at, updated_at)
               VALUES ('local-desktop', 'NOCOBASE', 'legacy-user', 'old-password', 1, 1, 1)"""
        )
    account = AuthenticationRepository(database).get_default_account(SystemType.NOCOBASE)
    assert account is not None
    assert account.password == "old-password"
    assert account.api_key == ""
    # Reopening the same database is safe and does not duplicate the migration.
    assert AuthenticationRepository(database).get_default_account(SystemType.NOCOBASE).id == account.id


def test_switch_to_key_keeps_account_identity_and_preserves_key_on_display_name_edit(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    repository = AuthenticationRepository(settings.auth_database_path)
    old = repository.save_account(SystemType.NOCOBASE, "legacy-user", "old-password")
    repository.save_session(old.id, "old-login-token")
    service = WebSettingsService(settings, tmp_path)
    saved = service.save_account(
        SystemType.NOCOBASE, account_id=old.id, account="", api_key="new-key",
        display_name="对接用户",
    )
    assert saved.id == old.id
    assert saved.api_key == "new-key"
    assert saved.password == ""
    assert repository.get_session(old.id) is None
    edited = service.save_account(
        SystemType.NOCOBASE, account_id=old.id, account="", display_name="新显示名称"
    )
    assert edited.api_key == "new-key"
    assert edited.display_name == "新显示名称"
    assert "new-key" not in repr(edited)


def test_web_key_configuration_never_returns_the_secret(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    coordinator = TaskCoordinator(max_workers=1)
    client = TestClient(create_app(settings=settings, logger=logging.getLogger("test"), coordinator=coordinator))
    try:
        saved = client.put(
            "/api/v1/settings/accounts/NOCOBASE",
            json={"api_key": "private-test-key", "display_name": "接口用户"},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["ready"] is True
        account_id = saved.json()["id"]
        detail = client.get(f"/api/v1/settings/accounts/NOCOBASE?account_id={account_id}")
        assert detail.status_code == 200
        assert detail.json()["api_key_saved"] is True
        assert detail.json()["api_key_mask"] == "******"
        assert detail.json()["password_saved"] is False
        listing = client.get("/api/v1/accounts")
        for response in (saved, detail, listing):
            assert "private-test-key" not in response.text
        preserved = client.put(
            "/api/v1/settings/accounts/NOCOBASE",
            json={"account_id": account_id, "display_name": "改名"},
        )
        assert preserved.status_code == 200
        account = AuthenticationRepository(settings.auth_database_path).get_default_account(SystemType.NOCOBASE)
        assert account.api_key == "private-test-key"
    finally:
        coordinator.close()


def test_query_uses_key_directly_without_password_login_or_token_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _save_key(settings, tmp_path)
    response = _Response(200, {"data": [], "meta": {"count": 0, "page": 1, "pageSize": 20, "totalPage": 0}})
    request = _transport(monkeypatch, response)
    result = NocoBaseApplicationQueryService(settings, logging.getLogger("test")).list_applications(page=1, page_size=20)
    assert result.records == ()
    assert len(request.calls) == 1
    assert request.calls[0][1]["headers"]["Authorization"] == "Bearer test-api-key"
    assert request.disposed and response.disposed


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_or_permission_is_reported_without_retry_or_secret_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int,
) -> None:
    settings = _settings(tmp_path)
    _save_key(settings, tmp_path)
    response = _Response(status, {"errors": [{"message": "remote error contains test-api-key", "code": "INVALID_TOKEN" if status == 401 else "FORBIDDEN"}]})
    request = _transport(monkeypatch, response)
    with pytest.raises(EhrmError) as failure:
        NocoBaseApplicationQueryService(settings, logging.getLogger("test")).list_applications(page=1, page_size=20)
    assert ("密钥" if status == 401 else "权限") in failure.value.message
    assert "test-api-key" not in failure.value.message
    assert len(request.calls) == 1
    assert request.disposed and response.disposed
    assert AuthenticationRepository(settings.auth_database_path).get_default_account(SystemType.NOCOBASE).api_key == "test-api-key"


def test_connection_test_accepts_unsaved_key_without_persisting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    response = _Response(200, {"data": [], "meta": {"count": 0, "page": 1, "pageSize": 1, "totalPage": 0}})
    request = _transport(monkeypatch, response)
    coordinator = TaskCoordinator(max_workers=1)
    client = TestClient(create_app(settings=settings, logger=logging.getLogger("test"), coordinator=coordinator))
    try:
        checked = client.post("/api/v1/settings/nocobase/test-connection", json={"api_key": "unsaved-key"})
        assert checked.status_code == 200, checked.text
        assert "成功" in checked.json()["message"]
        assert request.calls[0][1]["headers"]["Authorization"] == "Bearer unsaved-key"
        assert request.calls[0][1]["params"]["pageSize"] == "1"
        assert AuthenticationRepository(settings.auth_database_path).get_default_account(SystemType.NOCOBASE) is None
        assert "unsaved-key" not in checked.text
    finally:
        coordinator.close()


def test_legacy_password_is_not_a_configured_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    repository = AuthenticationRepository(settings.auth_database_path)
    repository.save_account(SystemType.NOCOBASE, "legacy-user", "old-password")
    _transport(monkeypatch, _Response(200, {}))
    with pytest.raises(ValueError, match="API 密钥"):
        NocoBaseApplicationQueryService(settings, logging.getLogger("test")).list_applications(page=1, page_size=1)


def test_connection_cli_uses_saved_key_without_printing_or_refreshing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    from ehrm.entrypoints import nocobase_login_cli

    settings = _settings(tmp_path)
    account = _save_key(settings, tmp_path)
    request = _transport(monkeypatch, _Response(200, {"data": [], "meta": {"count": 0, "page": 1, "pageSize": 1, "totalPage": 0}}))
    monkeypatch.setattr(nocobase_login_cli, "load_settings", lambda *_args, **_kwargs: settings)
    assert nocobase_login_cli.main(["--account-id", str(account.id)]) == 0
    output = capsys.readouterr().out
    assert "连接测试成功" in output
    assert "test-api-key" not in output
    assert len(request.calls) == 1
    assert AuthenticationRepository(settings.auth_database_path).get_session(account.id) is None


def test_key_rotation_preserves_other_systems_and_their_sessions(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = AuthenticationRepository(settings.auth_database_path)
    erp = repository.save_account(SystemType.ERP, "erp-user", "erp-password")
    rights = repository.save_account(SystemType.JSHRSS, "unit", "rights-password", secondary_account="mobile")
    for account in (erp, rights):
        repository.save_session(account.id, f"session-{account.id}")
    key_account = _save_key(settings, tmp_path)
    assert WebSettingsService(settings, tmp_path).account(key_account.id, SystemType.NOCOBASE).api_key == "test-api-key"
    rotated = repository.save_nocobase_api_key("replacement-key")
    assert rotated.id == key_account.id
    for account in (erp, rights):
        assert repository.get_account_by_id(account.id) == account
        assert repository.get_session(account.id).session_data == f"session-{account.id}"


@pytest.mark.parametrize("code", ["INVALID_TOKEN", "OTHER_ERROR"])
def test_http_200_error_does_not_echo_api_key_or_refresh_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str, caplog,
) -> None:
    settings = _settings(tmp_path)
    _save_key(settings, tmp_path)
    response = _Response(200, {"errors": [{"code": code, "message": "remote rejected test-api-key"}]})
    request = _transport(monkeypatch, response)
    with pytest.raises(EhrmError) as failure:
        NocoBaseApplicationQueryService(settings, logging.getLogger("test")).get_application(1)
    assert "test-api-key" not in str(failure.value)
    assert "test-api-key" not in caplog.text
    assert len(request.calls) == 1
    assert request.disposed and response.disposed
