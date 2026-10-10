from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ehrm.browser.captcha_policy import is_allowed_host_url
from ehrm.core.auth_repository import SystemAccount, SystemType
from ehrm.core.settings import load_settings
from ehrm.entrypoints.login_e2e_cli import main


def _account() -> SystemAccount:
    return SystemAccount(
        id=10,
        owner_id="local-desktop",
        system_type=SystemType.JSHRSS,
        account="test-credit-code",
        secondary_account="test-mobile",
        password="test-password",
        display_name="测试账号",
        profile_json='{"login_method":"direct"}',
        is_default=True,
        created_at=1,
        updated_at=1,
    )


def test_login_e2e_config_check_does_not_start_browser() -> None:
    with patch(
        "ehrm.entrypoints.login_e2e_cli.BrowserManager"
    ) as browser_manager, patch(
        "ehrm.entrypoints.login_e2e_cli.AuthenticationRepository"
    ) as repository_type:
        repository_type.return_value.get_default_account.return_value = None
        result = main(["--check-config"])

    assert result == 0
    browser_manager.assert_not_called()


def test_login_e2e_rejects_missing_saved_account() -> None:
    repository = Mock()
    repository.get_default_account.return_value = None
    with patch(
        "ehrm.entrypoints.login_e2e_cli.AuthenticationRepository",
        return_value=repository,
    ):
        result = main([])

    assert result == 2


def test_login_e2e_runs_complete_login_service_with_isolated_profile(
) -> None:
    settings = load_settings(Path("config/settings.toml"))
    account = _account()
    repository = Mock()
    repository.get_default_account.return_value = account

    page = SimpleNamespace(url=settings.site.rights_statement_url)
    browser = Mock()
    browser.__enter__ = Mock(return_value=browser)
    browser.__exit__ = Mock(return_value=None)
    browser.page = page
    service = Mock()
    service.page = page
    service.is_authenticated.return_value = False
    service.check_authenticated.return_value = True
    access_tokens = Mock()
    access_tokens.get_token.return_value = "captured-token"

    with (
        patch(
            "ehrm.entrypoints.login_e2e_cli.BrowserManager",
            return_value=browser,
        ) as browser_manager,
        patch(
            "ehrm.entrypoints.login_e2e_cli.LoginService",
            return_value=service,
        ) as login_service_type,
        patch(
            "ehrm.entrypoints.login_e2e_cli.create_rights_access_token_manager",
            return_value=access_tokens,
        ),
        patch(
            "ehrm.entrypoints.login_e2e_cli.AuthenticationRepository",
            return_value=repository,
        ),
        patch("builtins.input", return_value="") as wait_for_inspection,
    ):
        result = main(["--captcha-max-attempts", "1"])

    assert result == 0
    assert browser_manager.call_args is not None
    runtime_browser = browser_manager.call_args.args[0]
    assert runtime_browser.user_data_dir != settings.browser.user_data_dir
    assert runtime_browser.headless is settings.browser.headless
    assert "headless" not in browser_manager.call_args.kwargs
    expected_stealth = (
        settings.captcha.stealth_enabled
        and is_allowed_host_url(
            settings.site.login_url,
            settings.captcha.allowed_hosts,
        )
    )
    assert browser_manager.call_args.kwargs["stealth_enabled"] is expected_stealth
    assert login_service_type.call_args.args[1].captcha.max_attempts == 1
    service.ensure_authenticated.assert_called_once_with(
        username=account.account,
        mobile=account.secondary_account,
        password=account.password,
    )
    service.check_authenticated.assert_called_once_with()
    wait_for_inspection.assert_called_once()
