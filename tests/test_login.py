import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.login import LoginService
from ehrm.core.settings import load_settings


class FakeLocator:
    def __init__(self) -> None:
        self.first = self
        self.value = ""
        self.clicked = False

    def wait_for(self, **_: object) -> None:
        return None

    def fill(self, value: str) -> None:
        self.value = value

    def click(self) -> None:
        self.clicked = True


class FakePage:
    def __init__(self, settings) -> None:
        self.fields = {
            settings.login.credit_code: FakeLocator(),
            settings.login.mobile: FakeLocator(),
            settings.login.password: FakeLocator(),
            settings.login.submit: FakeLocator(),
        }

    def locator(self, selector: str) -> FakeLocator:
        return self.fields[selector]


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
