from __future__ import annotations

import base64
from dataclasses import replace
import logging
import time
from typing import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ehrm.browser.manager import BrowserManager
from ehrm.core.exceptions import ErpAuthenticationFailedError, TaskCancelledError
from ehrm.core.settings import AppSettings
from ehrm.modules.erp.codec import ErpQueryCodec
from ehrm.modules.erp.models import ErpCredentials


class ErpSession:
    """Owns one ERP browser context and its cookie-sharing API client."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self._settings = settings
        self._erp = settings.erp
        self._logger = logger
        self._browser: BrowserManager | None = None
        self._page: Page | None = None
        self._progress_callback = progress_callback
        self._cancel_check = cancel_check

    def __enter__(self) -> "ErpSession":
        browser_settings = replace(
            self._settings.browser,
            headless=self._erp.headless,
            slow_mo_ms=0,
            action_timeout_ms=self._settings.browser.action_timeout_ms,
            navigation_timeout_ms=self._erp.login_timeout_ms,
            user_data_dir=self._erp.user_data_dir,
            storage_state_path=self._erp.user_data_dir / "session-state.json",
        )
        self._browser = BrowserManager(browser_settings)
        self._browser.__enter__()
        self._page = self._select_page()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._browser is not None:
            self._browser.__exit__(exc_type, exc, traceback)
        self._browser = None
        self._page = None

    @property
    def page(self) -> Page:
        if self._browser is None:
            raise RuntimeError("ERP 会话尚未启动")
        if self._page is None or self._page.is_closed():
            self._page = self._select_page()
        return self._page

    @property
    def request(self):
        if self._browser is None or self._browser.context is None:
            raise RuntimeError("ERP 会话尚未启动")
        return self._browser.context.request

    def ensure_authenticated(
        self,
        credentials: ErpCredentials,
        *,
        force_login: bool = False,
    ) -> None:
        page = self.page
        try:
            self._raise_if_cancelled()
            self._progress("ERP：正在打开人力资源事务申请页面")
            page.goto(
                self._erp.application_url,
                wait_until="domcontentloaded",
                timeout=self._navigation_timeout_ms(),
            )
            self._raise_if_cancelled()
            if not force_login:
                self._progress("ERP：正在校验现有登录状态")
                if self._wait_for_codec(timeout_ms=10_000) and self._api_session_valid():
                    self._logger.info("ERP 已存在有效登录状态")
                    self._progress("ERP：登录状态有效")
                    return
                self._progress("ERP：登录状态已失效，正在自动重新登录")
            else:
                # A connection test must validate the credentials currently
                # entered by the operator. Reusing a valid persisted session
                # would make an arbitrary new password appear correct.
                self._progress("ERP：正在使用当前账号密码重新验证")
                self._logger.info("ERP 连接测试强制重新登录，不复用已有会话")
            self._clear_stale_auth_state()
            self._perform_login(credentials)
            self._raise_if_cancelled()
            self._progress("ERP：登录完成，正在进入申请页面")
            page.goto(
                self._erp.application_url,
                wait_until="domcontentloaded",
                timeout=self._navigation_timeout_ms(),
            )
            if not self._wait_for_codec(
                timeout_ms=min(self._erp.login_timeout_ms, 30_000)
            ):
                raise ErpAuthenticationFailedError(
                    "ERP 登录后未能进入人力资源事务申请页面"
                )
            self._progress("ERP：正在校验接口权限")
            self._log_auth_storage_names()
            if not self._api_session_valid():
                raise ErpAuthenticationFailedError(
                    "ERP 页面登录成功，但接口登录状态校验失败"
                )
            self._logger.info("ERP 自动登录成功")
            self._progress("ERP：自动登录成功")
        except ErpAuthenticationFailedError:
            raise
        except PlaywrightError as exc:
            raise ErpAuthenticationFailedError(
                "ERP 自动登录失败",
                details=str(exc),
            ) from exc

    def _perform_login(self, credentials: ErpCredentials) -> None:
        page = self.page
        self._raise_if_cancelled()
        self._progress("ERP：正在加载登录页面")
        username = page.locator(self._erp.login.username).first
        if not username.is_visible():
            page.goto(
                self._erp.login_url,
                wait_until="domcontentloaded",
                timeout=self._navigation_timeout_ms(),
            )

        username = page.locator(self._erp.login.username).first
        password = page.locator(self._erp.login.password).first
        submit = page.locator(self._erp.login.submit).first
        action_timeout = min(self._erp.login_timeout_ms, 30_000)
        username.wait_for(state="visible", timeout=action_timeout)
        password.wait_for(state="visible", timeout=action_timeout)
        submit.wait_for(state="visible", timeout=action_timeout)
        self._raise_if_cancelled()
        self._progress("ERP：正在提交账号密码")
        username.fill(credentials.username)
        password.fill(credentials.password)
        login_endpoint = f"{self._erp.base_url.rstrip('/')}/Account/Login"
        response_timeout = min(action_timeout, 15_000)
        try:
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.url.split("?", 1)[0].rstrip("/")
                    == login_endpoint.rstrip("/")
                ),
                timeout=response_timeout,
            ) as response_info:
                submit.click()
            response = response_info.value
        except PlaywrightTimeoutError as exc:
            raise ErpAuthenticationFailedError(
                "ERP 登录请求在 15 秒内没有返回，请检查网络或 ERP 服务状态"
            ) from exc

        try:
            payload = response.json()
        except (PlaywrightError, ValueError) as exc:
            # Some successful logins return an HTML redirect page instead of
            # the JSON body used by failed logins.  The cookies/navigation are
            # authoritative in that case; rejecting the response immediately
            # produces a false failure while leaving a valid session behind.
            if response.status < 400 and self._wait_for_login_state(username):
                self._logger.info(
                    "ERP 登录接口返回非 JSON 内容，但登录状态已建立 status=%s",
                    response.status,
                )
                return
            raise ErpAuthenticationFailedError(
                "ERP 登录接口返回了无法识别的内容"
            ) from exc
        success = payload.get("success") if isinstance(payload, dict) else None
        message = (
            str(payload.get("message") or "").strip()
            if isinstance(payload, dict)
            else ""
        )
        self._logger.info(
            "ERP 登录接口已响应 status=%s success=%s",
            response.status,
            success,
        )
        if response.status >= 400 or success is not True:
            raise ErpAuthenticationFailedError(
                message or "ERP 账号或密码校验未通过"
            )

        self._progress("ERP：账号校验通过，正在建立登录状态")
        if self._wait_for_login_state(username):
            return
        raise ErpAuthenticationFailedError(
            "ERP 账号校验成功，但登录状态未能写入，请稍后重试"
        )

    def _wait_for_login_state(
        self,
        username: Locator,
        *,
        timeout_ms: int | None = None,
    ) -> bool:
        state_timeout_ms = timeout_ms or min(self._erp.login_timeout_ms, 10_000)
        deadline = time.monotonic() + state_timeout_ms / 1000
        while time.monotonic() < deadline:
            self._raise_if_cancelled()
            if (
                self._has_auth_cookie()
                or "/WebCenter/" in self.page.url
                or not username.is_visible()
            ):
                return True
            self.page.wait_for_timeout(200)
        return False

    def _has_auth_cookie(self) -> bool:
        if self._browser is None or self._browser.context is None:
            return False
        try:
            names = {
                str(cookie.get("name", ""))
                for cookie in self._browser.context.cookies([self._erp.base_url])
            }
        except PlaywrightError:
            return False
        return "NCC_TOKEN" in names or "NCC_REFRESHTOKEN" in names

    def _wait_for_codec(self, *, timeout_ms: int) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            self._raise_if_cancelled()
            if ErpQueryCodec(self.page).is_available():
                return True
            self.page.wait_for_timeout(200)
        return False

    def _api_session_valid(self) -> bool:
        """Probes the same protected GridPageLoad endpoint used by queries."""
        try:
            encoded_swhere = ErpQueryCodec(self.page).encode_swhere(" 1=2 ")
            extparams = base64.b64encode(b'{"encodeswhere":"r4"}').decode("ascii")
            response = self.request.post(
                f"{self._erp.base_url.rstrip('/')}/Form/GridPageLoad",
                form={
                    "pageIndex": "0",
                    "pageSize": "1",
                    "sortField": "Code",
                    "sortOrder": "Desc",
                    "KeyWord": self._erp.business_keyword,
                    "KeyWordType": "BO",
                    "select": "",
                    "swhere": encoded_swhere,
                    "sort": "Code Desc",
                    "index": "0",
                    "size": "1",
                    "extparams": extparams,
                },
                headers={
                    "Accept": "text/plain, */*; q=0.01",
                    "Origin": self._erp.base_url,
                    "Referer": self._erp.application_url,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=min(self._erp.request_timeout_ms, 15_000),
            )
            try:
                status = response.status
                final_url = response.url
                if status in {401, 403} or "/Account/Login" in final_url:
                    self._logger.info(
                        "ERP 接口登录校验未通过 status=%s path=%s",
                        status,
                        final_url.split("?", 1)[0],
                    )
                    return False
                payload = response.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                message = str(payload.get("message", "")) if isinstance(payload, dict) else ""
                auth_message = message.lower()
                explicitly_unauthorized = any(
                    marker in auth_message
                    for marker in ("登录", "未授权", "unauthorized", "token", "令牌")
                )
                valid = (
                    200 <= status < 300
                    and isinstance(payload, dict)
                    and not explicitly_unauthorized
                )
                if not valid:
                    self._logger.info(
                        "ERP 接口登录校验响应无效 status=%s path=%s "
                        "success=%s data_type=%s message=%s",
                        status,
                        final_url.split("?", 1)[0],
                        payload.get("success") if isinstance(payload, dict) else None,
                        type(data).__name__,
                        message[:120],
                    )
                elif payload.get("success") is not True:
                    self._logger.info(
                        "ERP 接口会话有效但探测条件返回业务响应 "
                        "success=%s data_type=%s message=%s",
                        payload.get("success"),
                        type(data).__name__,
                        message[:120],
                    )
                return valid
            finally:
                response.dispose()
        except PlaywrightError as exc:
            self._logger.info(
                "ERP 接口登录校验请求失败 type=%s",
                type(exc).__name__,
            )
            return False
        except (TypeError, ValueError):
            self._logger.info("ERP 接口登录校验返回非 JSON 数据")
            return False

    def _clear_stale_auth_state(self) -> None:
        if self._browser is None or self._browser.context is None:
            return
        self._logger.info("ERP 接口会话无效，清除旧登录状态后重新登录")
        self._browser.context.clear_cookies()
        try:
            self.page.goto(self._erp.base_url, wait_until="domcontentloaded")
            self.page.evaluate(
                "() => { localStorage.clear(); sessionStorage.clear(); }"
            )
        except PlaywrightError:
            # Navigating to the explicit login URL below remains the fallback.
            pass

    def _log_auth_storage_names(self) -> None:
        if self._browser is None or self._browser.context is None:
            return
        try:
            cookie_names = sorted(
                cookie["name"]
                for cookie in self._browser.context.cookies([self._erp.base_url])
            )
            storage_keys = self.page.evaluate(
                "() => ({local: Object.keys(localStorage), "
                "session: Object.keys(sessionStorage)})"
            )
            self._logger.info(
                "ERP 登录存储已建立 cookies=%s local_storage_keys=%s "
                "session_storage_keys=%s",
                cookie_names,
                storage_keys.get("local", []) if isinstance(storage_keys, dict) else [],
                storage_keys.get("session", []) if isinstance(storage_keys, dict) else [],
            )
        except PlaywrightError:
            self._logger.info("ERP 登录存储名称读取失败")

    def _select_page(self) -> Page:
        if self._browser is None or self._browser.context is None:
            raise RuntimeError("ERP 浏览器尚未启动")
        for page in self._browser.context.pages:
            if page.url.startswith(self._erp.base_url):
                return page
        return self._browser.context.new_page()

    def _progress(self, text: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(text)

    def _raise_if_cancelled(self) -> None:
        if self._cancel_check is not None and self._cancel_check():
            raise TaskCancelledError("用户提前停止 ERP 上传")

    def _navigation_timeout_ms(self) -> int:
        return min(self._erp.login_timeout_ms, 30_000)
