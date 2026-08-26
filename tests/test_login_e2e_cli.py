from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ehrm.core.settings import load_settings
from ehrm.entrypoints.login_e2e_cli import main


def test_login_e2e_config_check_does_not_start_browser() -> None:
    with patch(
        "ehrm.entrypoints.login_e2e_cli.BrowserManager"
    ) as browser_manager:
        result = main(["--check-config"])

    assert result == 0
    browser_manager.assert_not_called()


def test_login_e2e_no_prompt_rejects_missing_credentials(monkeypatch) -> None:
    settings = load_settings(Path("config/settings.toml"))
    credentials = settings.rights_credentials
    monkeypatch.delenv(credentials.credit_code_env, raising=False)
    monkeypatch.delenv(credentials.mobile_env, raising=False)
    monkeypatch.delenv(credentials.password_env, raising=False)

    result = main(["--no-prompt"])

    assert result == 2


def test_login_e2e_runs_complete_login_service_with_isolated_profile(
    monkeypatch,
) -> None:
    settings = load_settings(Path("config/settings.toml"))
    credentials = settings.rights_credentials
    supplied = {
        credentials.credit_code_env: "test-credit-code",
        credentials.mobile_env: "test-mobile",
        credentials.password_env: "test-password",
    }
    for name, value in supplied.items():
        monkeypatch.setenv(name, value)

    page = SimpleNamespace(url=settings.site.login_url)
    browser = Mock()
    browser.__enter__ = Mock(return_value=browser)
    browser.__exit__ = Mock(return_value=None)
    browser.page = page
    service = Mock()
    service.is_authenticated.return_value = True

    with (
        patch(
            "ehrm.entrypoints.login_e2e_cli.BrowserManager",
            return_value=browser,
        ) as browser_manager,
        patch(
            "ehrm.entrypoints.login_e2e_cli.LoginService",
            return_value=service,
        ),
    ):
        result = main(["--no-prompt"])

    assert result == 0
    runtime_browser = browser_manager.call_args.args[0]
    assert runtime_browser.user_data_dir != settings.browser.user_data_dir
    service.ensure_authenticated.assert_called_once_with(
        username=supplied[credentials.credit_code_env],
        mobile=supplied[credentials.mobile_env],
        password=supplied[credentials.password_env],
    )
