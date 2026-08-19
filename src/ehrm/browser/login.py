from __future__ import annotations

import time
from collections.abc import Callable

from playwright.sync_api import Page

from ehrm.core.exceptions import AuthenticationFailedError, TaskCancelledError
from ehrm.core.settings import AppSettings


class LoginService:
    """Automates credentials and explicitly leaves security verification to a human."""

    def __init__(
        self,
        page: Page,
        settings: AppSettings,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.page = page
        self.settings = settings
        self.cancel_check = cancel_check

    def ensure_authenticated(
        self, username: str | None = None, password: str | None = None
    ) -> None:
        self._open_login_entry()
        if self.is_authenticated():
            return

        selectors = self.settings.login
        if username and selectors.username:
            self.page.locator(selectors.username).fill(username)
        if password and selectors.password:
            self.page.locator(selectors.password).fill(password)
        if username and password and selectors.submit:
            self.page.locator(selectors.submit).click()

        print("请在打开的浏览器中完成登录和安全验证，程序会自动继续……")
        deadline = time.monotonic() + self.settings.browser.manual_login_timeout_seconds
        while time.monotonic() < deadline:
            if self.cancel_check is not None and self.cancel_check():
                raise TaskCancelledError("用户在登录阶段停止任务")
            if self.is_authenticated():
                return
            self.page.wait_for_timeout(500)

        raise AuthenticationFailedError(
            "等待人工登录超时",
            details="请完成验证码后重试，或增加 manual_login_timeout_seconds",
        )

    def check_authenticated(self) -> bool:
        """Checks a persisted session without waiting for human input."""
        protected_url = self.settings.site.rights_statement_url
        if protected_url:
            self.page.goto(protected_url, wait_until="domcontentloaded")
            self.page.wait_for_timeout(1_500)
            return self.is_authenticated()
        self._open_login_entry()
        self.page.wait_for_timeout(1_000)
        return self.is_authenticated()

    def is_authenticated(self) -> bool:
        marker = self.settings.login.authenticated_marker
        if marker:
            try:
                locator = self.page.locator(marker).first
                if locator.count() > 0 and locator.is_visible():
                    return True
            except Exception:
                pass

        rights_url = self.settings.site.rights_statement_url
        return bool(rights_url and self.page.url.startswith(rights_url))

    def _open_login_entry(self) -> None:
        self.page.goto(self.settings.site.login_url, wait_until="domcontentloaded")
        if self.is_authenticated():
            return
        tab = self.settings.login.unit_login_tab
        if tab:
            try:
                locator = self.page.locator(tab).first
                if locator.count() > 0 and locator.is_visible():
                    locator.click()
                    self.page.wait_for_timeout(500)
            except Exception:
                # The login page may already be on the unit-login tab.
                pass
