from __future__ import annotations

import os
import time
import logging
from collections.abc import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ehrm.browser.captcha_policy import (
    is_allowed_host_url,
    url_without_sensitive_query,
)
from ehrm.core.exceptions import AuthenticationFailedError, TaskCancelledError
from ehrm.core.settings import AppSettings


_LOGGER = logging.getLogger("ehrm")


class LoginService:
    """Automates credentials and supports local-test CAPTCHA verification."""

    def __init__(
        self,
        page: Page,
        settings: AppSettings,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.page = page
        self.settings = settings
        self.cancel_check = cancel_check
        self._progress_callback = progress_callback
        self._manual_login_status: str | None = None
        self._context = getattr(page, "context", None)
        if self._context is not None:
            # Some login gateways replace the original tab with a newly opened
            # page. Keep the service attached to that page instead of retaining
            # a closed Playwright Page object.
            self._context.on("page", self._adopt_page)

    def _adopt_page(self, page: Page) -> None:
        self.page = page

    def _open_pages(self) -> list[Page]:
        if self._context is None:
            return [self.page]
        try:
            return [page for page in self._context.pages if not page.is_closed()]
        except PlaywrightError:
            return []

    def _active_page(self, *, prefer_latest: bool = False) -> Page:
        open_pages = self._open_pages()
        if prefer_latest and open_pages:
            self.page = open_pages[-1]
            return self.page
        try:
            if not self.page.is_closed():
                return self.page
        except AttributeError:
            # Lightweight test doubles do not expose Playwright lifecycle APIs.
            return self.page
        if not open_pages:
            raise AuthenticationFailedError(
                "登录浏览器页面已关闭",
                details="请确认登录页没有自行关闭，并重新运行完整登录测试",
            )
        self.page = open_pages[-1]
        return self.page

    def _wait_for_timeout(self, timeout_ms: int) -> None:
        page = self._active_page()
        try:
            page.wait_for_timeout(timeout_ms)
        except PlaywrightError:
            replacement = self._active_page()
            if replacement is page:
                raise
            replacement.wait_for_timeout(timeout_ms)

    def ensure_authenticated(
        self,
        username: str | None = None,
        password: str | None = None,
        mobile: str | None = None,
    ) -> None:
        self._manual_login_status = None
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
        submitted = self._autofill_and_submit(
            credit_code=credit_code,
            mobile=mobile_number,
            password=resolved_password,
        )
        captcha_solved = submitted and self._try_automated_captcha()

        if not captcha_solved:
            self._progress(
                self._manual_login_status
                or "请在打开的浏览器中完成登录和安全验证，程序会自动继续……"
            )
        deadline = time.monotonic() + self.settings.browser.manual_login_timeout_seconds
        while time.monotonic() < deadline:
            if self.cancel_check is not None and self.cancel_check():
                raise TaskCancelledError("用户在登录阶段停止任务")
            if self.is_authenticated():
                return
            self._wait_for_timeout(500)

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
        """Fills unit credentials and submits the login form."""
        if not all((credit_code, mobile, password)):
            missing = []
            if not credit_code:
                missing.append("统一社会信用代码/单位编号/机构编号")
            if not mobile:
                missing.append("证件号码/移动电话")
            if not password:
                missing.append("密码")
            self._manual_login_status = (
                "智慧人社登录信息不完整，已跳过自动填写："
                + "、".join(missing)
            )
            return False

        selectors = self.settings.login
        if not all(
            (selectors.credit_code, selectors.mobile, selectors.password, selectors.submit)
        ):
            return False

        last_error: PlaywrightError | None = None
        for attempt in range(2):
            page = self._active_page(prefer_latest=True)
            try:
                credit_field = page.locator(selectors.credit_code).first
                mobile_field = page.locator(selectors.mobile).first
                password_field = page.locator(selectors.password).first
                submit = page.locator(selectors.submit).first
                timeout = self.settings.browser.action_timeout_ms
                credit_field.wait_for(state="visible", timeout=timeout)
                mobile_field.wait_for(state="visible", timeout=timeout)
                password_field.wait_for(state="visible", timeout=timeout)
                submit.wait_for(state="visible", timeout=timeout)
                credit_field.fill(credit_code)
                mobile_field.fill(mobile)
                password_field.fill(password)
                submit.click()
                self._progress("登录信息已自动填写，正在检查安全验证……")
                return True
            except PlaywrightError as exc:
                last_error = exc
                replacement = self._active_page(prefer_latest=True)
                if attempt == 0 and replacement is not page:
                    _LOGGER.info("登录页已切换，改用新页面继续自动填写")
                    continue
                break

        _LOGGER.error("智慧人社登录信息自动填写失败: %s", last_error)
        self._manual_login_status = (
            "未能自动定位登录输入框，请手动填写登录信息并完成安全验证……"
        )
        return False

    def _try_automated_captcha(self) -> bool:
        """Runs automatic clicking only for an explicitly allowed host."""
        if not self.settings.captcha.enabled:
            self._manual_login_status = (
                "人工验证：验证码自动验证未启用，请在浏览器中完成安全验证"
            )
            return False

        page = self._active_page(prefer_latest=True)
        if not is_allowed_host_url(
            page.url, self.settings.captcha.allowed_hosts
        ):
            _LOGGER.info("当前页面不在验证码自动化主机白名单，继续由人工完成")
            self._manual_login_status = (
                "人工验证：当前登录环境不启用自动验证，请在浏览器中完成，"
                "完成后程序会自动继续"
            )
            return False

        # Import lazily so normal remote/manual login does not initialize OpenCV.
        from ehrm.browser.captcha import (
            CaptchaAutomationError,
            CaptchaRateLimitedError,
            CaptchaSolver,
        )

        solver = CaptchaSolver(
            page,
            self.settings.captcha,
            progress_callback=self._progress,
        )
        try:
            solved = solver.solve()
        except CaptchaRateLimitedError as exc:
            _LOGGER.warning("%s；请等待页面允许后人工验证", exc)
            self._manual_login_status = (
                f"人工验证：{exc}；请等待页面允许后再手动验证"
            )
            return False
        except (CaptchaAutomationError, PlaywrightError, ValueError) as exc:
            _LOGGER.warning("验证码自动验证失败，已转人工处理：%s", exc)
            self._manual_login_status = (
                f"人工验证：自动验证失败，已切换为人工处理：{exc}"
            )
            return False
        if solved:
            self._progress("自动验证：验证码已通过，正在等待登录结果……")
        return solved

    def _progress(self, message: str) -> None:
        if self._progress_callback is None:
            print(message)
            return
        try:
            self._progress_callback(message)
        except Exception:
            _LOGGER.exception("发送登录进度消息失败")

    def check_authenticated(self) -> bool:
        """Checks a persisted session without waiting for human input."""
        protected_url = self.settings.site.rights_statement_url
        if protected_url:
            page = self._active_page()
            page.goto(protected_url, wait_until="domcontentloaded")
            self._wait_for_timeout(1_500)
            return self.is_authenticated()
        self._open_login_entry()
        self._wait_for_timeout(1_000)
        return self.is_authenticated()

    def is_authenticated(self) -> bool:
        marker = self.settings.login.authenticated_marker
        pages = self._open_pages() or [self._active_page()]
        if marker:
            for page in reversed(pages):
                try:
                    locator = page.locator(marker).first
                    if locator.count() > 0 and locator.is_visible():
                        self.page = page
                        return True
                except Exception:
                    pass

        rights_url = self.settings.site.rights_statement_url
        if not rights_url:
            return False
        for page in reversed(pages):
            try:
                if page.url.startswith(rights_url):
                    self.page = page
                    return True
            except Exception:
                pass
        return False

    def _open_login_entry(self) -> None:
        page = self._active_page()
        try:
            page.goto(self.settings.site.login_url, wait_until="domcontentloaded")
        except PlaywrightError:
            replacement = self._active_page(prefer_latest=True)
            if replacement is page:
                raise
        else:
            self._active_page(prefer_latest=True)
        self._report_browser_features(self._active_page())
        if self.is_authenticated():
            return
        self._ensure_login_tab_active(
            self.settings.login.unit_login_tab,
            "单位登录",
        )
        self._ensure_login_tab_active(
            self.settings.login.account_password_tab,
            "账号密码",
        )

    def _ensure_login_tab_active(self, selector: str, label: str) -> None:
        if not selector:
            raise AuthenticationFailedError(f"未配置“{label}”登录方式定位器")

        page = self._active_page()
        candidates = page.locator(selector)
        timeout = self.settings.browser.action_timeout_ms
        try:
            count = candidates.count()
            if count != 1:
                raise AuthenticationFailedError(
                    f"无法唯一定位“{label}”登录方式",
                    details=f"当前可见匹配数量：{count}；定位器：{selector}",
                )
            tab = candidates.first
            tab.wait_for(state="visible", timeout=timeout)
            if not self._tab_is_active(tab):
                tab.click()

            deadline = time.monotonic() + timeout / 1000.0
            while time.monotonic() < deadline:
                if self._tab_is_active(tab):
                    message = f"登录方式：已确认“{label}”处于激活状态"
                    _LOGGER.info(message)
                    self._progress(message)
                    return
                self._wait_for_timeout(100)
        except AuthenticationFailedError:
            raise
        except PlaywrightError as exc:
            raise AuthenticationFailedError(
                f"选择“{label}”登录方式失败",
                details=str(exc),
            ) from exc

        raise AuthenticationFailedError(
            f"选择“{label}”登录方式后未进入激活状态",
            details=f"未检测到 CSS 类 tab-active；定位器：{selector}",
        )

    @staticmethod
    def _tab_is_active(tab: object) -> bool:
        return bool(
            tab.evaluate(  # type: ignore[attr-defined]
                "element => element.classList.contains('tab-active')"
            )
        )

    def _report_browser_features(self, page: Page) -> None:
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return
        try:
            webdriver = evaluate("navigator.webdriver")
        except PlaywrightError:
            _LOGGER.debug("读取登录页浏览器特征失败", exc_info=True)
            return
        webdriver_value = str(webdriver).lower()
        allowed = is_allowed_host_url(
            page.url, self.settings.captcha.allowed_hosts
        )
        message = (
            "浏览器特征：登录页 URL="
            f"{url_without_sensitive_query(page.url)}，"
            f"allowed_hosts={'命中' if allowed else '未命中'}，"
            f"stealth_enabled={str(self.settings.captcha.stealth_enabled).lower()}，"
            f"navigator.webdriver={webdriver_value}"
        )
        _LOGGER.info(message)
        self._progress(message)
