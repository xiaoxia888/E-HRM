from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ehrm.browser.manager import BrowserManager
from ehrm.core.settings import load_settings


def test_browser_manager_forwards_configured_engine_and_channel(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        Path("config/settings.toml"), data_root=tmp_path
    ).browser
    context = Mock()
    context.pages = []
    browser_type = Mock()
    browser_type.launch_persistent_context.return_value = context
    playwright = SimpleNamespace(
        chromium=browser_type if settings.engine == "chromium" else Mock(),
        firefox=browser_type if settings.engine == "firefox" else Mock(),
        webkit=browser_type if settings.engine == "webkit" else Mock(),
        stop=Mock(),
    )
    starter = Mock()
    starter.start.return_value = playwright

    with patch("ehrm.browser.manager.sync_playwright", return_value=starter):
        with BrowserManager(settings) as manager:
            assert manager.context is context

    launch = browser_type.launch_persistent_context.call_args.kwargs
    assert launch["user_data_dir"] == settings.user_data_dir
    if settings.channel:
        assert launch["channel"] == settings.channel
    else:
        assert "channel" not in launch


def test_browser_manager_limits_stealth_script_to_allowed_hosts(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        Path("config/settings.toml"), data_root=tmp_path
    )
    context = Mock()
    context.pages = []
    browser_type = Mock()
    browser_type.launch_persistent_context.return_value = context
    playwright = SimpleNamespace(
        chromium=browser_type,
        firefox=Mock(),
        webkit=Mock(),
        stop=Mock(),
    )
    starter = Mock()
    starter.start.return_value = playwright
    stealth = Mock()
    stealth.script_payload = "globalThis.__ehrmStealthApplied = true;"

    with (
        patch("ehrm.browser.manager.sync_playwright", return_value=starter),
        patch("playwright_stealth.Stealth", return_value=stealth),
    ):
        with BrowserManager(
            settings.browser,
            stealth_allowed_hosts=settings.captcha.allowed_hosts,
        ):
            pass

    script = context.add_init_script.call_args.kwargs["script"]
    for host in settings.captcha.allowed_hosts:
        assert host in script
    assert settings.site.login_url.split("://", 1)[1].split(":", 1)[0] in script
    assert "__ehrmStealthApplied" in script


def test_browser_manager_does_not_load_stealth_without_allowed_hosts(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        Path("config/settings.toml"), data_root=tmp_path
    ).browser
    context = Mock()
    context.pages = []
    browser_type = Mock()
    browser_type.launch_persistent_context.return_value = context
    playwright = SimpleNamespace(
        chromium=browser_type,
        firefox=Mock(),
        webkit=Mock(),
        stop=Mock(),
    )
    starter = Mock()
    starter.start.return_value = playwright

    with patch("ehrm.browser.manager.sync_playwright", return_value=starter):
        with BrowserManager(settings):
            pass

    context.add_init_script.assert_not_called()
