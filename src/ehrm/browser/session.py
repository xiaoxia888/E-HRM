from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import json
import os

from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.login import LoginService
from ehrm.browser.manager import BrowserManager
from ehrm.core.settings import AppSettings


@contextmanager
def authenticated_browser(
    settings: AppSettings,
    *,
    username: str | None = None,
    password: str | None = None,
    mobile: str | None = None,
) -> Iterator[BrowserManager]:
    """Uses headless mode when a saved session is valid, otherwise hands off to a human."""

    if settings.browser.silent_session_check:
        try:
            with BrowserManager(settings.browser, headless=True) as checker:
                _restore_storage_state(checker, settings)
                if LoginService(checker.page, settings).check_authenticated():
                    try:
                        yield checker
                    finally:
                        _save_storage_state(checker, settings)
                    return
        except PlaywrightError:
            # A site can refuse headless mode. The visible human-login path remains usable.
            pass

    print("登录状态已失效，即将打开可见浏览器供人工登录。")
    with BrowserManager(settings.browser, headless=False) as browser:
        _restore_storage_state(browser, settings)
        LoginService(browser.page, settings).ensure_authenticated(
            username,
            password,
            mobile,
        )
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
