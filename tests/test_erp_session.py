from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ehrm.core.exceptions import ErpAuthenticationFailedError
from ehrm.core.settings import load_settings
from ehrm.modules.erp.models import ErpCredentials
from ehrm.modules.erp.session import ErpSession


class FakeLocator:
    def __init__(self) -> None:
        self.value = ""
        self.clicked = False

    @property
    def first(self) -> "FakeLocator":
        return self

    def is_visible(self) -> bool:
        return True

    def wait_for(self, **kwargs) -> None:
        return None

    def fill(self, value: str) -> None:
        self.value = value

    def click(self) -> None:
        self.clicked = True


class FakeLoginResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status = 200
        self.url = "https://erp.njncc.com/Account/Login"
        self.request = type("Request", (), {"method": "POST"})()

    def json(self) -> dict:
        return self._payload


class FakeHtmlLoginResponse(FakeLoginResponse):
    def json(self) -> dict:
        raise ValueError("HTML response")


class FakeResponseInfo:
    def __init__(self, response: FakeLoginResponse) -> None:
        self.value = response

    def __enter__(self) -> "FakeResponseInfo":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class FakePage:
    def __init__(self, payload: dict) -> None:
        self.url = "https://erp.njncc.com/"
        self.username = FakeLocator()
        self.password = FakeLocator()
        self.submit = FakeLocator()
        self.response = FakeLoginResponse(payload)

    def is_closed(self) -> bool:
        return False

    def locator(self, selector: str) -> FakeLocator:
        if "password" in selector or "userpass" in selector:
            return self.password
        if "登录" in selector or "submit" in selector:
            return self.submit
        return self.username

    def goto(self, *args, **kwargs) -> None:
        return None

    def expect_response(self, predicate, **kwargs) -> FakeResponseInfo:
        assert predicate(self.response)
        return FakeResponseInfo(self.response)

    def wait_for_timeout(self, milliseconds: int) -> None:
        return None


class FakeContext:
    def __init__(self, *, authenticated: bool) -> None:
        self.authenticated = authenticated

    def cookies(self, urls) -> list[dict]:
        return [{"name": "NCC_TOKEN"}] if self.authenticated else []


class FakeBrowser:
    def __init__(self, *, authenticated: bool) -> None:
        self.context = FakeContext(authenticated=authenticated)


def _session(tmp_path: Path, payload: dict, *, authenticated: bool) -> tuple[ErpSession, FakePage]:
    settings = load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path,
    )
    session = ErpSession(settings, logging.getLogger("test.erp.session"))
    page = FakePage(payload)
    session._browser = FakeBrowser(authenticated=authenticated)
    session._page = page
    return session, page


def test_login_returns_immediately_after_success_response_and_cookie(
    tmp_path: Path,
) -> None:
    session, page = _session(tmp_path, {"success": True}, authenticated=True)

    session._perform_login(ErpCredentials(username="user", password="pass"))

    assert page.username.value == "user"
    assert page.password.value == "pass"
    assert page.submit.clicked


def test_login_surfaces_server_message_without_waiting_for_page_timeout(
    tmp_path: Path,
) -> None:
    session, _ = _session(
        tmp_path,
        {"success": False, "message": "账号或密码错误"},
        authenticated=False,
    )

    with pytest.raises(ErpAuthenticationFailedError, match="账号或密码错误"):
        session._perform_login(ErpCredentials(username="user", password="bad"))


def test_login_accepts_non_json_response_when_auth_cookie_was_created(
    tmp_path: Path,
) -> None:
    session, page = _session(tmp_path, {}, authenticated=True)
    page.response = FakeHtmlLoginResponse({})

    session._perform_login(ErpCredentials(username="user", password="pass"))

    assert page.submit.clicked
