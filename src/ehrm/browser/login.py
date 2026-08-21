from __future__ import annotations

import os
import time
import logging
from collections.abc import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ehrm.core.exceptions import AuthenticationFailedError, TaskCancelledError
from ehrm.core.settings import AppSettings


_LOGGER = logging.getLogger("ehrm")


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
        self,
        username: str | None = None,
        password: str | None = None,
        mobile: str | None = None,
    ) -> None:
        self._open_login_entry()
        if self.is_authenticated():
            return

        credentials = self.settings.rights_credentials
        credit_code = (
            username
            or credentials.credit_code
            or os.getenv(credentials.credit_code_env)
        )
        mobile_number = (
            mobile
            or credentials.mobile
            or os.getenv(credentials.mobile_env)
        )
        resolved_password = (
            password
            or credentials.password
            or os.getenv(credentials.password_env)
        )
        self._autofill_and_submit(
            credit_code=credit_code,
            mobile=mobile_number,
            password=resolved_password,
        )

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

    def _autofill_and_submit(
        self,
        *,
        credit_code: str | None,
        mobile: str | None,
        password: str | None,
    ) -> bool:
        """Fills unit credentials and submits, while leaving CAPTCHA to a human."""
        if not all((credit_code, mobile, password)):
            missing = []
            if not credit_code:
                missing.append("统一社会信用代码/单位编号/机构编号")
            if not mobile:
                missing.append("证件号码/移动电话")
            if not password:
                missing.append("密码")
            print(
                "智慧人社登录信息不完整，已跳过自动填写："
                + "、".join(missing)
            )
            return False

        selectors = self.settings.login
        if not all(
            (selectors.credit_code, selectors.mobile, selectors.password, selectors.submit)
        ):
            return False

        try:
            credit_field = self.page.locator(selectors.credit_code).first
            mobile_field = self.page.locator(selectors.mobile).first
            password_field = self.page.locator(selectors.password).first
            submit = self.page.locator(selectors.submit).first
            timeout = self.settings.browser.action_timeout_ms
            credit_field.wait_for(state="visible", timeout=timeout)
            mobile_field.wait_for(state="visible", timeout=timeout)
            password_field.wait_for(state="visible", timeout=timeout)
            submit.wait_for(state="visible", timeout=timeout)
            credit_field.fill(credit_code)
            mobile_field.fill(mobile)
            password_field.fill(password)
            submit.click()
            print("登录信息已自动填写，请完成安全验证……")
            return True
        except PlaywrightError as exc:
            _LOGGER.error("智慧人社登录信息自动填写失败: %s", exc)
            print("未能自动定位登录输入框，请手动填写登录信息并完成安全验证……")
            return False

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
        account_tab = self.settings.login.account_password_tab
        if account_tab:
            try:
                locator = self.page.locator(account_tab).last
                if locator.count() > 0 and locator.is_visible():
                    locator.click()
                    self.page.wait_for_timeout(500)
            except Exception:
                # Some page versions select account/password login by default.
                pass
