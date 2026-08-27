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
    def __init__(self, *, active: bool = False, activate_on_click: bool = True) -> None:
        self.first = self
        self.value = ""
        self.clicked = False
        self.active = active
        self.activate_on_click = activate_on_click

    def count(self) -> int:
        return 1

    def wait_for(self, **_: object) -> None:
        return None

    def fill(self, value: str) -> None:
        self.value = value

    def click(self) -> None:
        self.clicked = True
        if self.activate_on_click:
            self.active = True

    def evaluate(self, _expression: str) -> bool:
        return self.active


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
        "账号登录成功，Access-Token 已安全保存，正在确认登录状态……"
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

    with patch.dict(sys.modules, {"ehrm.browser.captcha": None}):
        solved = service._try_automated_captcha()

    assert solved is False
