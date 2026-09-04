from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import json
import os

from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.access_token import (
    create_rights_access_token_manager,
)
from ehrm.browser.captcha_policy import is_allowed_host_url
from ehrm.browser.login import LoginService
from ehrm.browser.manager import BrowserManager
from ehrm.core.settings import AppSettings
from ehrm.core.auth_repository import AuthenticationRepository, SystemType


@contextmanager
def authenticated_browser(
    settings: AppSettings,
    *,
    username: str | None = None,
    password: str | None = None,
    mobile: str | None = None,
) -> Iterator[BrowserManager]:
    """Uses the configured browser mode and restores any saved login session."""

    stealth_enabled = (
        settings.captcha.stealth_enabled
        and is_allowed_host_url(
            settings.site.login_url,
            settings.captcha.allowed_hosts,
        )
    )
    credentials = settings.rights_credentials
    saved_account = AuthenticationRepository(
        settings.auth_database_path
    ).get_default_account(SystemType.JSHRSS)
    token_manager = create_rights_access_token_manager(
        settings.auth_database_path,
        username
        or credentials.credit_code
        or (saved_account.account if saved_account else ""),
        mobile
        or credentials.mobile
        or (saved_account.secondary_account if saved_account else ""),
        password=(
            password
            or credentials.password
            or (saved_account.password if saved_account else "")
        ),
    )

    if settings.browser.silent_session_check:
        try:
            with BrowserManager(
                settings.browser,
                headless=True,
                stealth_enabled=stealth_enabled,
            ) as checker:
                _restore_storage_state(checker, settings)
                if LoginService(
                    checker.page,
                    settings,
                    access_token_manager=token_manager,
                ).check_authenticated():
                    try:
                        yield checker
                    finally:
                        _save_storage_state(checker, settings)
                    return
        except PlaywrightError:
            # A site can refuse headless mode. The visible human-login path remains usable.
            pass

    browser_mode = "无头浏览器" if settings.browser.headless else "可见浏览器"
    print(f"登录状态已失效，即将打开{browser_mode}完成登录。")
    with BrowserManager(
        settings.browser,
        stealth_enabled=stealth_enabled,
    ) as browser:
        _restore_storage_state(browser, settings)
        LoginService(
            browser.page,
            settings,
            access_token_manager=token_manager,
        ).ensure_authenticated(username, password, mobile)
        _save_storage_state(browser, settings)
        print("登录成功，程序将在当前浏览器中继续自动执行。")
        try:
            yield browser
        finally:
            _save_storage_state(browser, settings)


def _restore_storage_state(browser: BrowserManager, settings: AppSettings) -> None:
    path = settings.browser.storage_state_path
    if browser.context is None or not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cookies = payload.get("cookies", [])
        if isinstance(cookies, list) and cookies:
            browser.context.add_cookies(cookies)
    except (OSError, ValueError, PlaywrightError):
        # The persistent profile remains the fallback if the snapshot is invalid.
        return


def _save_storage_state(browser: BrowserManager, settings: AppSettings) -> None:
    path = settings.browser.storage_state_path
    if browser.context is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    browser.context.storage_state(path=path)
    os.chmod(path, 0o600)
