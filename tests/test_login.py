from dataclasses import replace
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.access_token import AccessTokenManager, MemoryAccessTokenStore
from ehrm.browser.login import LoginService
from ehrm.core.exceptions import AuthenticationFailedError
from ehrm.core.settings import load_settings


class FakeLocator:
    def __init__(
        self,
        *,
        active: bool = False,
        activate_on_click: bool = True,
        visible: bool = True,
    ) -> None:
        self.first = self
        self.value = ""
        self.clicked = False
        self.active = active
        self.activate_on_click = activate_on_click
        self.visible = visible

    def count(self) -> int:
        return 1

    def nth(self, index: int):
        if index != 0:
            raise IndexError(index)
        return self

    def wait_for(self, **_: object) -> None:
        return None

    def is_visible(self) -> bool:
        return self.visible

    def fill(self, value: str) -> None:
        self.value = value

    def click(self) -> None:
        self.clicked = True
        if self.activate_on_click:
            self.active = True

    def evaluate(self, _expression: str) -> bool:
        return self.active


class CallbackFakeLocator(FakeLocator):
    def __init__(self, callback, *, visible: bool = True) -> None:
        super().__init__(visible=visible)
        self._callback = callback

    def click(self) -> None:
        super().click()
        self._callback()


class FakeLocatorCollection:
    def __init__(self, *items: FakeLocator) -> None:
        self.items = items
        self.first = items[0]

    def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> FakeLocator:
        return self.items[index]


class DelayedFakeLocator(FakeLocator):
    """Simulates a Vue tab that appears after DOMContentLoaded."""

    def __init__(self) -> None:
        super().__init__()
        self.ready = False

    def count(self) -> int:
        return 1 if self.ready else 0

    def wait_for(self, **_: object) -> None:
        self.ready = True


class FakePage:
    def __init__(self, settings) -> None:
        self.fields = {
            settings.login.unit_login_tab: FakeLocator(),
            settings.login.account_password_tab: FakeLocator(),
            settings.login.credit_code: FakeLocator(),
            settings.login.mobile: FakeLocator(),
            settings.login.password: FakeLocator(),
            settings.login.submit: FakeLocator(),
        }

    def locator(self, selector: str) -> FakeLocator:
        return self.fields[selector]

    def wait_for_timeout(self, _timeout_ms: int) -> None:
        return None


class FakeGovernmentEntryPage(FakePage):
    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.url = "about:blank"
        self.navigated_urls: list[str] = []
        self.fields[settings.government_login_selectors.entry_button] = (
            CallbackFakeLocator(
                lambda: setattr(
                    self,
                    "url",
                    settings.government_login.landing_url
                    + "?uuid=fresh-session&gotoUrl=test",
                )
            )
        )
        for selector in (
            settings.government_login_selectors.corporate_tab,
            settings.government_login_selectors.username,
            settings.government_login_selectors.password,
            settings.government_login_selectors.captcha_input,
            settings.government_login_selectors.captcha_image,
            settings.government_login_selectors.agreement,
            settings.government_login_selectors.submit,
        ):
            self.fields[selector] = FakeLocator()

    def goto(self, url: str, **_: object) -> None:
        self.navigated_urls.append(url)
        self.url = url

    def is_closed(self) -> bool:
        return False

    def wait_for_load_state(self, *_: object, **__: object) -> None:
        return None

    def evaluate(self, _expression: str) -> bool:
        return False


class FakeLoginResponse:
    def __init__(
        self,
        settings,
        *,
        status: int,
        payload: dict[str, object],
    ) -> None:
        login_url = urlsplit(settings.site.login_url)
        self.url = urlunsplit(
            (
                login_url.scheme,
                login_url.netloc,
                settings.site.unit_password_login_path,
                "",
                "",
            )
        )
        self.status = status
        self.request = SimpleNamespace(method="POST")
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class FakeGovernmentLoginResponse(FakeLoginResponse):
    def __init__(self, settings, *, payload: dict[str, object], status: int = 200):
        super().__init__(settings, status=status, payload=payload)
        login_url = urlsplit(settings.government_login.landing_url)
        self.url = urlunsplit(
            (
                login_url.scheme,
                login_url.netloc,
                settings.government_login.login_api_path,
                "",
                "",
            )
        )


def test_login_method_tabs_are_clicked_and_verified_active(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = FakePage(settings)
    service = LoginService(page, settings)  # type: ignore[arg-type]

    service._ensure_login_tab_active(settings.login.unit_login_tab, "单位登录")
    service._ensure_login_tab_active(
        settings.login.account_password_tab,
        "账号密码",
    )

    assert page.fields[settings.login.unit_login_tab].clicked is True
    assert page.fields[settings.login.unit_login_tab].active is True
    assert page.fields[settings.login.account_password_tab].clicked is True
    assert page.fields[settings.login.account_password_tab].active is True


def test_login_method_waits_for_vue_render_before_counting(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = FakePage(settings)
    delayed_tab = DelayedFakeLocator()
    page.fields[settings.login.unit_login_tab] = delayed_tab
    service = LoginService(page, settings)  # type: ignore[arg-type]

    service._ensure_login_tab_active(settings.login.unit_login_tab, "单位登录")

    assert delayed_tab.ready is True
    assert delayed_tab.clicked is True
    assert delayed_tab.active is True


def test_login_method_tab_must_reach_active_state(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    settings = replace(
        settings,
        browser=replace(settings.browser, action_timeout_ms=1),
    )
    page = FakePage(settings)
    page.fields[settings.login.unit_login_tab] = FakeLocator(
        activate_on_click=False
    )
    service = LoginService(page, settings)  # type: ignore[arg-type]

    with pytest.raises(AuthenticationFailedError, match="未进入激活状态"):
        service._ensure_login_tab_active(
            settings.login.unit_login_tab,
            "单位登录",
        )


def test_unit_login_autofills_three_fields_and_submits(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = FakePage(settings)
    service = LoginService(page, settings)  # type: ignore[arg-type]

    submitted = service._autofill_and_submit(
        credit_code="91320000TEST000001",
        mobile="13800000000",
        password="secret",
    )

    assert submitted is True
    assert page.fields[settings.login.credit_code].value == "91320000TEST000001"
    assert page.fields[settings.login.mobile].value == "13800000000"
    assert page.fields[settings.login.password].value == "secret"
    assert page.fields[settings.login.submit].clicked is True


def test_unit_password_login_error_response_is_forwarded(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    updates: list[str] = []
    service = LoginService(  # type: ignore[arg-type]
        FakePage(settings),
        settings,
        progress_callback=updates.append,
    )
    response = FakeLoginResponse(
        settings,
        status=500,
        payload={
            "appcode": "test-error-code",
            "msg": "测试账号密码错误",
            "map": {},
        },
    )

    service._capture_login_response(response)  # type: ignore[arg-type]

    with pytest.raises(AuthenticationFailedError, match="测试账号密码错误") as error:
        service._raise_login_failure()
    assert error.value.details == "HTTP=500，appcode=test-error-code"
    assert updates == [
        "登录失败：测试账号密码错误（HTTP=500，appcode=test-error-code）"
    ]


def test_successful_login_response_saves_access_token(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    updates: list[str] = []
    store = MemoryAccessTokenStore()
    manager = AccessTokenManager("test-account", store)
    service = LoginService(  # type: ignore[arg-type]
        FakePage(settings),
        settings,
        progress_callback=updates.append,
        access_token_manager=manager,
    )
    response = FakeLoginResponse(
        settings,
        status=200,
        payload={
            "appcode": "0",
            "msg": "登录成功",
            "map": {"Access-Token": "test-secret-token"},
        },
    )

    service._capture_login_response(response)  # type: ignore[arg-type]

    service._raise_login_failure()
    assert manager.get_token() == "test-secret-token"
    assert AccessTokenManager("test-account", store).get_token() == (
        "test-secret-token"
    )
    assert updates == [
        "账号登录成功，Access-Token 已保存到应用数据库，正在确认登录状态……"
    ]
    assert all("test-secret-token" not in update for update in updates)


def test_successful_login_without_access_token_is_rejected(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    manager = AccessTokenManager("test-account", MemoryAccessTokenStore())
    service = LoginService(  # type: ignore[arg-type]
        FakePage(settings),
        settings,
        access_token_manager=manager,
    )
    response = FakeLoginResponse(
        settings,
        status=200,
        payload={"appcode": "0", "msg": "登录成功", "map": {}},
    )

    service._capture_login_response(response)  # type: ignore[arg-type]

    with pytest.raises(AuthenticationFailedError, match="缺少 Access-Token"):
        service._raise_login_failure()
    assert manager.get_token() is None


def test_business_error_is_rejected_even_with_http_200(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    service = LoginService(FakePage(settings), settings)  # type: ignore[arg-type]
    response = FakeLoginResponse(
        settings,
        status=200,
        payload={"appcode": "test-error-code", "msg": "测试业务错误"},
    )

    service._capture_login_response(response)  # type: ignore[arg-type]

    with pytest.raises(AuthenticationFailedError, match="测试业务错误"):
        service._raise_login_failure()


def test_government_login_is_opened_from_jshrss_unit_login(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = FakeGovernmentEntryPage(settings)
    service = LoginService(page, settings)  # type: ignore[arg-type]

    landing_page = service._open_government_login_entry()

    assert landing_page is page
    assert page.navigated_urls == [settings.site.login_url]
    assert page.fields[settings.login.unit_login_tab].clicked is True
    assert page.fields[
        settings.government_login_selectors.entry_button
    ].clicked is True
    assert page.url.startswith(settings.government_login.landing_url + "?")


def test_government_entry_uses_visible_unit_login_shortcut(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = FakeGovernmentEntryPage(settings)
    hidden_personal_entry = CallbackFakeLocator(lambda: None, visible=False)
    visible_unit_entry = CallbackFakeLocator(
        lambda: setattr(
            page,
            "url",
            settings.government_login.landing_url + "?uuid=unit-login",
        )
    )
    page.fields[settings.government_login_selectors.entry_button] = (
        FakeLocatorCollection(hidden_personal_entry, visible_unit_entry)
    )
    service = LoginService(page, settings)  # type: ignore[arg-type]

    service._open_government_login_entry()

    assert hidden_personal_entry.clicked is False
    assert visible_unit_entry.clicked is True


def test_government_saved_session_skips_login_form_and_finishes_sso(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = FakeGovernmentEntryPage(settings)
    page.fields[settings.government_login_selectors.entry_button] = (
        CallbackFakeLocator(
            lambda: setattr(page, "url", settings.government_login.target_url)
        )
    )
    service = LoginService(page, settings)  # type: ignore[arg-type]

    with patch.object(
        service,
        "_finish_reused_government_session",
    ) as finish_session:
        service._ensure_government_authenticated(
            username="government-user",
            password="government-password",
        )

    finish_session.assert_called_once_with()
    assert page.fields[
        settings.government_login_selectors.corporate_tab
    ].clicked is False


def test_government_landing_url_ignores_dynamic_query_but_checks_host_and_path(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    service = LoginService(FakePage(settings), settings)  # type: ignore[arg-type]

    assert service._is_government_landing_url(
        settings.government_login.landing_url
        + "?uuid=fresh-session&gotoUrl=%2Fapi%2Fcheck"
    )
    assert not service._is_government_landing_url(
        "https://www.jszwfw.gov.cn/jsjis/front/error.do"
    )
    assert not service._is_government_landing_url(
        "https://example.com/jsjis/front/login.do"
    )


def test_government_login_form_requires_all_recorded_controls(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = FakeGovernmentEntryPage(settings)
    service = LoginService(page, settings)  # type: ignore[arg-type]

    username, password = service._wait_for_government_login_form(page)  # type: ignore[arg-type]

    assert username is page.fields[settings.government_login_selectors.username]
    assert password is page.fields[settings.government_login_selectors.password]


def test_government_login_captcha_error_is_retryable(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    service = LoginService(FakePage(settings), settings)  # type: ignore[arg-type]
    response = FakeGovernmentLoginResponse(
        settings,
        payload={
            "params": {"isShowVerifyCode": "1"},
            "message": "验证码输入有误，看不清可点击验证码更换",
            "success": False,
        },
    )

    service._capture_login_response(response)  # type: ignore[arg-type]

    service._raise_login_failure()
    assert service._government_result == "captcha_error"


def test_government_login_password_error_stops_immediately(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    service = LoginService(FakePage(settings), settings)  # type: ignore[arg-type]
    response = FakeGovernmentLoginResponse(
        settings,
        payload={
            "params": {},
            "message": "用户名或密码不正确，注意区分大小写",
            "success": False,
        },
    )

    service._capture_login_response(response)  # type: ignore[arg-type]

    with pytest.raises(AuthenticationFailedError, match="用户名或密码不正确"):
        service._raise_login_failure()


def test_government_login_empty_http_200_waits_for_redirect(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    service = LoginService(FakePage(settings), settings)  # type: ignore[arg-type]
    response = FakeGovernmentLoginResponse(settings, payload={}, status=200)

    service._capture_login_response(response)  # type: ignore[arg-type]

    service._raise_login_failure()
    assert service._government_result == "redirecting"


def test_government_login_explicit_empty_failure_waits_for_redirect(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    service = LoginService(FakePage(settings), settings)  # type: ignore[arg-type]
    response = FakeGovernmentLoginResponse(
        settings,
        payload={"params": {}, "message": "", "success": False},
        status=200,
    )

    service._capture_login_response(response)  # type: ignore[arg-type]

    service._raise_login_failure()
    assert service._government_result == "redirecting"


def test_government_login_target_requires_exact_home_page(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    marker = SimpleNamespace(
        count=lambda: 1,
        is_visible=lambda: True,
    )
    page = SimpleNamespace(
        url=settings.government_login.target_url,
        locator=lambda _selector: SimpleNamespace(first=marker),
    )
    service = LoginService(page, settings)  # type: ignore[arg-type]

    assert service.is_government_target_reached() is True
    assert service.is_government_view_ready() is True

    page.url = "https://rs.jshrss.jiangsu.gov.cn/web/thirdLogin?ticket=test"
    assert service.is_government_target_reached() is False
    assert service.is_government_view_ready() is False

    page.url = "https://example.com/index/"
    assert service.is_government_target_reached() is False


def test_sso_access_token_is_only_captured_from_jshrss_host(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    store = MemoryAccessTokenStore()
    manager = AccessTokenManager("selected-account", store)
    service = LoginService(  # type: ignore[arg-type]
        FakePage(settings),
        settings,
        access_token_manager=manager,
    )
    trusted = SimpleNamespace(
        url="https://rs.jshrss.jiangsu.gov.cn/api/example",
        headers={"access-token": "captured-token"},
    )
    untrusted = SimpleNamespace(
        url="https://example.invalid/api/example",
        headers={"access-token": "untrusted-token"},
    )

    service._capture_access_token_request(untrusted)  # type: ignore[arg-type]
    assert manager.get_token() is None
    service._capture_access_token_request(trusted)  # type: ignore[arg-type]

    assert manager.get_token() == "captured-token"


def test_unit_password_login_listener_ignores_other_paths(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    service = LoginService(FakePage(settings), settings)  # type: ignore[arg-type]
    response = FakeLoginResponse(
        settings,
        status=500,
        payload={"appcode": "test-error-code", "msg": "不应捕获"},
    )
    response.url += "/other"

    service._capture_login_response(response)  # type: ignore[arg-type]

    service._raise_login_failure()


def test_unit_login_does_not_submit_when_credentials_are_incomplete(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = FakePage(settings)
    service = LoginService(page, settings)  # type: ignore[arg-type]

    submitted = service._autofill_and_submit(
        credit_code="91320000TEST000001",
        mobile=None,
        password="secret",
    )

    assert submitted is False
    assert page.fields[settings.login.submit].clicked is False


def test_unit_login_continues_on_replacement_page(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    replacement = FakePage(settings)

    class Context:
        def __init__(self) -> None:
            self.pages = []
            self.callback = None

        def on(self, _event: str, callback) -> None:
            self.callback = callback

    context = Context()

    class ClosingLocator(FakeLocator):
        def wait_for(self, **_: object) -> None:
            original.closed = True
            context.pages.append(replacement)
            assert context.callback is not None
            context.callback(replacement)
            raise PlaywrightError("original page closed")

    class LifecyclePage(FakePage):
        def __init__(self) -> None:
            super().__init__(settings)
            self.context = context
            self.closed = False
            self.fields[settings.login.credit_code] = ClosingLocator()

        def is_closed(self) -> bool:
            return self.closed

    original = LifecyclePage()
    replacement.context = context
    replacement.is_closed = lambda: False  # type: ignore[attr-defined]
    context.pages.append(original)
    service = LoginService(original, settings)  # type: ignore[arg-type]

    submitted = service._autofill_and_submit(
        credit_code="test-credit-code",
        mobile="test-mobile",
        password="test-password",
    )

    assert submitted is True
    assert service.page is replacement
    assert replacement.fields[settings.login.credit_code].value == "test-credit-code"
    assert replacement.fields[settings.login.mobile].value == "test-mobile"
    assert replacement.fields[settings.login.password].value == "test-password"
    assert replacement.fields[settings.login.submit].clicked is True


def test_unlisted_host_skips_captcha_without_importing_opencv(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    configured = urlsplit(settings.site.login_url)
    unlisted_url = urlunsplit(
        (configured.scheme, f"{uuid4().hex}.invalid", configured.path, "", "")
    )
    page = SimpleNamespace(url=unlisted_url)
    service = LoginService(page, settings)  # type: ignore[arg-type]

    with (
        patch.dict(sys.modules, {"ehrm.browser.captcha": None}),
        pytest.raises(AuthenticationFailedError, match="自动验证未执行"),
    ):
        service._try_automated_captcha()

    assert service._manual_login_status is None
