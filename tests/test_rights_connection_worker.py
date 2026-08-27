import logging
from pathlib import Path

import pytest


pytest.importorskip("PySide6")

from ehrm.core.settings import load_settings
from ehrm.core.exceptions import CaptchaRateLimitedAuthenticationError
from ehrm.gui import rights_connection_worker as worker_module


def test_rights_connection_test_uses_isolated_profile_and_requires_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path / "runtime",
    )
    observed: dict[str, object] = {}

    class FakeAccessTokenManager:
        def __init__(self, account_key: str) -> None:
            observed["account_key"] = account_key
            self.token = None

        def get_token(self):
            return self.token

    class FakeBrowserManager:
        def __init__(self, browser_settings, **_kwargs) -> None:
            observed["browser_settings"] = browser_settings
            self.page = object()

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class FakeLoginService:
        def __init__(
            self,
            _page,
            _settings,
            _cancel_check,
            _progress,
            access_tokens,
        ) -> None:
            self.access_tokens = access_tokens

        def ensure_authenticated(self, *, username, mobile, password) -> None:
            observed["credentials"] = (username, mobile, password)
            self.access_tokens.token = "test-access-token"

    monkeypatch.setattr(
        worker_module,
        "AccessTokenManager",
        FakeAccessTokenManager,
    )
    monkeypatch.setattr(
        worker_module,
        "BrowserManager",
        FakeBrowserManager,
    )
    monkeypatch.setattr(
        worker_module,
        "LoginService",
        FakeLoginService,
    )
    succeeded: list[bool] = []
    failed: list[tuple[str, str]] = []
    worker = worker_module.RightsConnectionWorker(
        settings,
        logging.getLogger("test.rights-connection"),
        "test-credit",
        "test-mobile",
        "test-password",
    )
    worker.succeeded.connect(lambda: succeeded.append(True))
    worker.failed.connect(
        lambda summary, details: failed.append((summary, details))
    )

    worker.run()

    runtime_browser = observed["browser_settings"]
    assert runtime_browser.user_data_dir != settings.browser.user_data_dir
    assert observed["credentials"] == (
        "test-credit",
        "test-mobile",
        "test-password",
    )
    assert succeeded == [True]
    assert failed == []


def test_captcha_rate_limit_is_forwarded_to_frontend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path / "runtime",
    )

    class FakeAccessTokenManager:
        def __init__(self, _account_key: str) -> None:
            pass

        def get_token(self):
            return None

    class FakeBrowserManager:
        def __init__(self, _browser_settings, **_kwargs) -> None:
            self.page = object()

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class FakeLoginService:
        def __init__(self, *_args) -> None:
            pass

        def ensure_authenticated(self, **_kwargs) -> None:
            raise CaptchaRateLimitedAuthenticationError(
                "验证码操作过于频繁，请等待 1 小时后再试",
                details="验证码服务返回 errorCode=12",
            )

    monkeypatch.setattr(
        worker_module,
        "AccessTokenManager",
        FakeAccessTokenManager,
    )
    monkeypatch.setattr(
        worker_module,
        "BrowserManager",
        FakeBrowserManager,
    )
    monkeypatch.setattr(
        worker_module,
        "LoginService",
        FakeLoginService,
    )
    failed: list[tuple[str, str]] = []
    worker = worker_module.RightsConnectionWorker(
        settings,
        logging.getLogger("test.rights-rate-limit"),
        "test-credit",
        "test-mobile",
        "test-password",
    )
    worker.failed.connect(
        lambda summary, details: failed.append((summary, details))
    )

    worker.run()

    assert failed == [
        (
            "验证码操作过于频繁，请等待 1 小时后再试",
            "验证码服务返回 errorCode=12",
        )
    ]
