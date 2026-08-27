from __future__ import annotations

import os
import time
import logging
from collections.abc import Callable
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Response

from ehrm.browser.access_token import (
    AccessTokenManager,
    build_access_token_account_key,
)
from ehrm.browser.captcha_policy import (
    is_allowed_host_url,
    url_without_sensitive_query,
)
from ehrm.core.exceptions import (
    AuthenticationFailedError,
    CaptchaRateLimitedAuthenticationError,
    EhrmError,
    TaskCancelledError,
)
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
        access_token_manager: AccessTokenManager | None = None,
    ) -> None:
        self.page = page
        self.settings = settings
        self.cancel_check = cancel_check
        self._progress_callback = progress_callback
        self._access_token_manager = access_token_manager
        self._manual_login_status: str | None = None
        self._login_failure: AuthenticationFailedError | None = None
        self._login_succeeded = False
        self._response_listener_page_ids: set[int] = set()
        self._context = getattr(page, "context", None)
        self._listen_for_login_response(page)
        if self._context is not None:
            # Some login gateways replace the original tab with a newly opened
            # page. Keep the service attached to that page instead of retaining
            # a closed Playwright Page object.
            self._context.on("page", self._adopt_page)

    def _adopt_page(self, page: Page) -> None:
        self.page = page
        self._listen_for_login_response(page)

    def _listen_for_login_response(self, page: object) -> None:
        page_id = id(page)
        if page_id in self._response_listener_page_ids:
            return
        on = getattr(page, "on", None)
        if not callable(on):
            return
        on("response", self._capture_login_response)
        self._response_listener_page_ids.add(page_id)

    def _capture_login_response(self, response: Response) -> None:
        """Captures the unit-password result without raising in an event hook."""
        try:
            if not self._is_unit_password_login_response(response):
                return
            try:
                payload = response.json()
            except (PlaywrightError, ValueError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}

            appcode = str(payload.get("appcode") or "").strip()
            message = str(payload.get("msg") or "").strip()
            status = response.status
            _LOGGER.info(
                "单位账号密码登录接口响应 HTTP=%s appcode=%s msg=%s",
                status,
                appcode or "无",
                message or "无",
            )

            business_failed = bool(appcode and appcode != "0")
            if status >= 400 or business_failed:
                visible_message = message or f"账号登录接口返回 HTTP {status}"
                details = f"HTTP={status}，appcode={appcode or '无'}"
                self._login_failure = AuthenticationFailedError(
                    visible_message,
                    details=details,
                )
                self._progress(
                    f"登录失败：{visible_message}（{details}）"
                )
            elif appcode == "0":
                self._store_successful_access_token(payload)
            else:
                summary = f"HTTP={status}"
                if appcode:
                    summary += f"，appcode={appcode}"
                self._progress(f"账号登录接口已返回（{summary}），正在确认登录状态……")
        except Exception:
            # Playwright event callbacks must not interrupt its internal event loop.
            _LOGGER.exception("解析单位账号密码登录接口响应失败")

    def _store_successful_access_token(self, payload: dict[str, object]) -> None:
        raw_map = payload.get("map")
        response_map = raw_map if isinstance(raw_map, dict) else {}
        token = str(response_map.get("Access-Token") or "").strip()
        if not token:
            self._login_failure = AuthenticationFailedError(
                "登录成功响应中缺少 Access-Token",
                details="appcode=0，但 map.Access-Token 为空",
            )
            self._progress("登录失败：登录成功响应中缺少 Access-Token")
            return
        if self._access_token_manager is None:
            self._login_failure = AuthenticationFailedError(
                "Access-Token 管理器尚未初始化"
            )
            self._progress("登录失败：Access-Token 管理器尚未初始化")
            return
        try:
            self._access_token_manager.save_token(token)
        except (EhrmError, OSError, ValueError) as exc:
            self._login_failure = AuthenticationFailedError(
                "Access-Token 安全保存失败",
                details=str(exc),
            )
            self._progress(f"登录失败：Access-Token 安全保存失败：{exc}")
            return
        _LOGGER.info("智慧人社 Access-Token 已保存到内存和安全存储")
        self._login_succeeded = True
        self._progress(
            "账号登录成功，Access-Token 已安全保存，正在确认登录状态……"
        )

    def _is_unit_password_login_response(self, response: Response) -> bool:
        try:
            if response.request.method.upper() != "POST":
                return False
            actual = urlsplit(response.url)
            configured = urlsplit(self.settings.site.login_url)
            expected_path = self.settings.site.unit_password_login_path.rstrip("/")
            return (
                actual.scheme.casefold() == configured.scheme.casefold()
                and actual.netloc.casefold() == configured.netloc.casefold()
                and actual.path.rstrip("/") == expected_path
            )
        except (AttributeError, ValueError):
            return False

    def _raise_login_failure(self) -> None:
        if self._login_failure is not None:
            raise self._login_failure

    @property
    def access_token_manager(self) -> AccessTokenManager | None:
        return self._access_token_manager

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
        self._login_failure = None
        self._login_succeeded = False
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
        if self._access_token_manager is None:
            account_key = build_access_token_account_key(
                self.settings.site.login_url,
                credit_code,
                mobile_number,
            )
            self._access_token_manager = AccessTokenManager(account_key)

        self._open_login_entry()
        if self.is_authenticated():
            return

        submitted = self._autofill_and_submit(
            credit_code=credit_code,
            mobile=mobile_number,
            password=resolved_password,
        )
        if self.settings.captcha.enabled and not submitted:
            raise AuthenticationFailedError(
                "自动登录信息提交失败",
                details=(
                    self._manual_login_status
                    or "验证码自动验证已启用，不进入人工登录等待"
                ),
            )

        captcha_solved = submitted and self._try_automated_captcha()
        self._raise_login_failure()

        if not captcha_solved:
            self._progress(
                self._manual_login_status
                or "请在打开的浏览器中完成登录和安全验证，程序会自动继续……"
            )
        if self.settings.captcha.enabled:
            completion_timeout_seconds = (
                self.settings.browser.action_timeout_ms / 1000.0
            )
        else:
            completion_timeout_seconds = (
                self.settings.browser.manual_login_timeout_seconds
            )
        deadline = time.monotonic() + completion_timeout_seconds
        while time.monotonic() < deadline:
            self._raise_login_failure()
            if self.cancel_check is not None and self.cancel_check():
                raise TaskCancelledError("用户在登录阶段停止任务")
            if self._login_succeeded or self.is_authenticated():
                return
            self._wait_for_timeout(500)

        if self.settings.captcha.enabled:
            raise AuthenticationFailedError(
                "等待自动登录结果超时",
                details=(
                    "验证码已经自动处理，但在 action_timeout_ms 内没有收到"
                    "登录成功响应或页面登录标志"
                ),
            )
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
            message = "当前页面主机不在验证码自动验证白名单"
            _LOGGER.warning("%s，已停止登录流程", message)
            self._progress(f"自动验证：{message}，已停止登录流程")
            raise AuthenticationFailedError(
                "验证码自动验证未执行",
                details=(
                    f"{message}；enabled=true 时不会进入人工验证等待"
                ),
            )

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
            _LOGGER.warning("验证码自动验证已停止：%s", exc)
            visible_message = "验证码操作过于频繁，请等待 1 小时后再试"
            self._progress(f"自动验证：{visible_message}")
            raise CaptchaRateLimitedAuthenticationError(
                visible_message,
                details=(
                    f"{exc}；自动验证和人工等待均已停止，请在 1 小时后重试"
                ),
            ) from exc
        except (CaptchaAutomationError, PlaywrightError, ValueError) as exc:
            _LOGGER.warning("验证码自动验证失败，已停止登录流程：%s", exc)
            self._progress(f"自动验证：失败，已停止登录流程：{exc}")
            raise AuthenticationFailedError(
                "验证码自动验证失败",
                details=str(exc),
            ) from exc
        if not solved:
            self._progress("自动验证：未通过，已停止登录流程")
            raise AuthenticationFailedError(
                "验证码自动验证未通过",
                details="enabled=true，已跳过人工验证等待",
            )
        self._progress("自动验证：验证码已通过，正在等待登录结果……")
        return True

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
            # The login tabs are rendered asynchronously by Vue after
            # DOMContentLoaded. Wait for the configured occurrence before
            # checking uniqueness; an immediate count can transiently be 0.
            tab = candidates.first
            tab.wait_for(state="visible", timeout=timeout)
            count = candidates.count()
            if count != 1:
                raise AuthenticationFailedError(
                    f"无法唯一定位“{label}”登录方式",
                    details=f"当前可见匹配数量：{count}；定位器：{selector}",
                )
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
            details=(
                "未检测到 CSS 类 tab-active 或 tab-active-r；"
                f"定位器：{selector}"
            ),
        )

    @staticmethod
    def _tab_is_active(tab: object) -> bool:
        return bool(
            tab.evaluate(  # type: ignore[attr-defined]
                "element => {"
                "const classes = element.closest('li.tab')?.classList;"
                "return Boolean("
                "classes?.contains('tab-active') || "
                "classes?.contains('tab-active-r')"
                ");"
                "}"
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
