from pathlib import Path

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
