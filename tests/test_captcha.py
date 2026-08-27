from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import cv2
import numpy as np
import pytest

from ehrm.browser.captcha import (
    CaptchaRateLimitedError,
    CaptchaSolver,
    image_point_to_page,
    is_allowed_host_url,
)
from ehrm.browser.captcha_policy import url_without_sensitive_query
from ehrm.browser.captcha_matcher import CaptchaMatch
from ehrm.browser.login import LoginService
from ehrm.core.exceptions import AuthenticationFailedError
from ehrm.core.settings import AppSettings, CaptchaSettings, load_settings


def _captcha_settings() -> CaptchaSettings:
    return load_settings(Path("config/settings.toml")).captcha


def _unused_port() -> int:
    minimum_unprivileged_port = 1024
    maximum_tcp_port = 65535
    available_port_count = maximum_tcp_port - minimum_unprivileged_port + 1
    return minimum_unprivileged_port + uuid4().int % available_port_count


def _url_for_host(settings: AppSettings, host: str) -> str:
    configured = urlsplit(settings.site.login_url)
    display_host = f"[{host}]" if ":" in host else host
    return urlunsplit(
        (
            configured.scheme,
            f"{display_host}:{_unused_port()}",
            configured.path,
            "",
            "",
        )
    )


def test_allowed_hosts_ignore_protocol_and_port_but_match_host_exactly() -> None:
    settings = load_settings(Path("config/settings.toml"))
    for host in settings.captcha.allowed_hosts:
        assert is_allowed_host_url(
            _url_for_host(settings, host), settings.captcha.allowed_hosts
        )

    unlisted_host = f"{uuid4().hex}.invalid"
    assert not is_allowed_host_url(
        _url_for_host(settings, unlisted_host), settings.captcha.allowed_hosts
    )


def test_log_safe_captcha_url_removes_query_and_fragment() -> None:
    assert url_without_sensitive_query(
        "https://127.0.0.1:8000/captcha/image?sess=sensitive#fragment"
    ) == "https://127.0.0.1:8000/captcha/image"


def test_image_point_is_scaled_to_page_coordinates() -> None:
    point = image_point_to_page(
        image_point=(320, 240),
        image_size=(640, 480),
        element_box={"x": 100.0, "y": 50.0, "width": 340.0, "height": 242.0},
    )
    assert point == (270.0, 171.0)


def test_every_paced_click_uses_configured_delay_range() -> None:
    settings = load_settings(Path("config/settings.toml"))
    delay = (
        settings.captcha.click_delay_min_ms
        + settings.captcha.click_delay_max_ms
    ) // 2
    page = SimpleNamespace(
        url=_url_for_host(settings, settings.captcha.allowed_hosts[0]),
        wait_for_timeout=Mock(),
    )
    sampler = Mock(return_value=delay)
    solver = CaptchaSolver(  # type: ignore[arg-type]
        page,
        _captcha_settings(),
        delay_sampler=sampler,
    )

    solver._random_pause()

    sampler.assert_called_once_with(
        settings.captcha.click_delay_min_ms,
        settings.captcha.click_delay_max_ms,
    )
    page.wait_for_timeout.assert_called_once_with(delay)


def test_click_offset_is_randomized_inside_matched_box() -> None:
    settings = load_settings(Path("config/settings.toml"))
    page = SimpleNamespace(
        url=_url_for_host(settings, settings.captcha.allowed_hosts[0]),
        mouse=SimpleNamespace(click=Mock()),
        wait_for_timeout=Mock(),
    )
    offset_sampler = Mock(side_effect=[2, -1])
    solver = CaptchaSolver(  # type: ignore[arg-type]
        page,
        settings.captcha,
        delay_sampler=Mock(return_value=settings.captcha.click_delay_min_ms),
        offset_sampler=offset_sampler,
    )
    background = SimpleNamespace(
        bounding_box=Mock(
            return_value={
                "x": 100.0,
                "y": 50.0,
                "width": 340.0,
                "height": 242.0,
            }
        )
    )
    challenge = SimpleNamespace(
        background=background,
        background_image=np.zeros((480, 640, 3), dtype=np.uint8),
    )
    match = CaptchaMatch(
        index=1,
        score=0.1,
        center=(320, 240),
        matched_bbox=(300, 220, 340, 260),
        scale=1.0,
        angle=0.0,
        aspect_ratio=1.0,
    )

    click_points = solver._click_matches(  # type: ignore[arg-type]
        challenge,
        [match],
    )

    expected_limit = min(settings.captcha.click_offset_max_px, 9)
    offset_sampler.assert_has_calls(
        [call(-expected_limit, expected_limit)] * 2
    )
    page.mouse.click.assert_called_once_with(272.0, 170.0)
    assert len(click_points) == 1
    assert click_points[0].sequence == 1
    assert click_points[0].image_x == 324
    assert click_points[0].image_y == 238


def test_captcha_diagnostics_save_sources_and_actual_click_result(
    tmp_path: Path,
) -> None:
    app_settings = load_settings(Path("config/settings.toml"))
    settings = replace(
        app_settings.captcha,
        diagnostic_images_enabled=True,
        diagnostic_output_dir=tmp_path / "captcha-diagnostics",
    )
    page = SimpleNamespace(
        url=_url_for_host(app_settings, settings.allowed_hosts[0]),
        mouse=SimpleNamespace(click=Mock()),
        wait_for_timeout=Mock(),
    )
    solver = CaptchaSolver(  # type: ignore[arg-type]
        page,
        settings,
        delay_sampler=Mock(return_value=settings.click_delay_min_ms),
        offset_sampler=Mock(side_effect=[2, -1]),
    )
    target_image = np.full((30, 90, 3), 220, dtype=np.uint8)
    background_image = np.full((480, 640, 3), 245, dtype=np.uint8)
    challenge = SimpleNamespace(
        target_image=target_image,
        background_image=background_image,
        background=SimpleNamespace(
            bounding_box=Mock(
                return_value={
                    "x": 100.0,
                    "y": 50.0,
                    "width": 340.0,
                    "height": 242.0,
                }
            )
        ),
    )
    match = CaptchaMatch(
        index=1,
        score=0.1,
        center=(320, 240),
        matched_bbox=(300, 220, 340, 260),
        scale=1.0,
        angle=0.0,
        aspect_ratio=1.0,
    )

    attempt_dir = solver._save_diagnostic_sources(  # type: ignore[arg-type]
        challenge,
        1,
    )
    click_points = solver._click_matches(  # type: ignore[arg-type]
        challenge,
        [match],
    )
    solver._save_diagnostic_result(
        attempt_dir,
        background_image,
        click_points,
        matches=[match],
    )

    assert attempt_dir is not None
    assert {path.name for path in attempt_dir.iterdir()} == {
        "1_target.png",
        "2_background.png",
        "3_result.png",
        "13_selected_matches.png",
    }
    saved_target = cv2.imread(str(attempt_dir / "1_target.png"))
    saved_background = cv2.imread(str(attempt_dir / "2_background.png"))
    saved_result = cv2.imread(str(attempt_dir / "3_result.png"))
    saved_matches = cv2.imread(
        str(attempt_dir / "13_selected_matches.png")
    )
    assert np.array_equal(saved_target, target_image)
    assert np.array_equal(saved_background, background_image)
    assert saved_result is not None
    assert not np.array_equal(saved_result, background_image)
    assert saved_matches is not None
    assert not np.array_equal(saved_matches, background_image)
    assert click_points[0].image_x == 324
    assert click_points[0].image_y == 238


def test_captcha_diagnostics_do_not_write_when_disabled(tmp_path: Path) -> None:
    output_dir = tmp_path / "captcha-diagnostics"
    settings = replace(
        _captcha_settings(),
        diagnostic_images_enabled=False,
        diagnostic_output_dir=output_dir,
    )
    solver = CaptchaSolver(  # type: ignore[arg-type]
        SimpleNamespace(url="https://localhost"),
        settings,
    )
    challenge = SimpleNamespace(
        target_image=np.zeros((10, 10, 3), dtype=np.uint8),
        background_image=np.zeros((20, 20, 3), dtype=np.uint8),
    )

    assert solver._save_diagnostic_sources(  # type: ignore[arg-type]
        challenge,
        1,
    ) is None
    assert not output_dir.exists()


def test_login_service_uses_solver_on_allowed_page(tmp_path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = SimpleNamespace(
        url=_url_for_host(settings, settings.captcha.allowed_hosts[0])
    )
    solver = Mock()
    solver.is_supported_page.return_value = True
    solver.solve.return_value = True

    with patch(
        "ehrm.browser.captcha.CaptchaSolver",
        return_value=solver,
    ):
        solved = LoginService(page, settings)._try_automated_captcha()  # type: ignore[arg-type]

    assert solved is True
    solver.solve.assert_called_once_with()


def test_login_service_skips_solver_on_unlisted_page(tmp_path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = SimpleNamespace(url=_url_for_host(settings, f"{uuid4().hex}.invalid"))
    solver = Mock()
    solver.is_supported_page.return_value = False

    with patch(
        "ehrm.browser.captcha.CaptchaSolver",
        return_value=solver,
    ), pytest.raises(AuthenticationFailedError, match="自动验证未执行"):
        LoginService(page, settings)._try_automated_captcha()  # type: ignore[arg-type]

    solver.solve.assert_not_called()


def test_solver_stops_immediately_when_verification_is_rate_limited() -> None:
    settings = load_settings(Path("config/settings.toml"))
    page = SimpleNamespace(
        url=_url_for_host(settings, settings.captcha.allowed_hosts[0])
    )
    solver = CaptchaSolver(page, settings.captcha)  # type: ignore[arg-type]
    frame = object()
    challenge = SimpleNamespace(
        frame=frame,
        target_image=object(),
        background_image=object(),
        target_url="target",
        background_url="background",
    )
    solver._find_frame = Mock(return_value=frame)  # type: ignore[method-assign]
    solver._load_challenge = Mock(return_value=challenge)  # type: ignore[method-assign]
    solver._click_matches = Mock()  # type: ignore[method-assign]
    solver._confirm_and_wait = Mock(  # type: ignore[method-assign]
        return_value={
            "errorCode": "12",
            "randstr": "",
            "ticket": "",
            "errMessage": "",
            "sess": "sensitive-session-value",
        }
    )

    with (
        patch("ehrm.browser.captcha.match_captcha_symbols", return_value=[]),
        pytest.raises(CaptchaRateLimitedError, match="操作过于频繁"),
    ):
        solver.solve()

    solver._confirm_and_wait.assert_called_once_with(frame)


def test_rate_limit_message_is_forwarded_to_login_progress(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = SimpleNamespace(
        url=_url_for_host(settings, settings.captcha.allowed_hosts[0])
    )
    updates: list[str] = []
    service = LoginService(  # type: ignore[arg-type]
        page,
        settings,
        progress_callback=updates.append,
    )
    service._open_login_entry = Mock()  # type: ignore[method-assign]
    service.is_authenticated = Mock(return_value=False)  # type: ignore[method-assign]
    service._autofill_and_submit = Mock(return_value=True)  # type: ignore[method-assign]
    service._wait_for_timeout = Mock()  # type: ignore[method-assign]
    solver = Mock()
    solver.solve.side_effect = CaptchaRateLimitedError("测试环境操作过于频繁")

    with (
        patch("ehrm.browser.captcha.CaptchaSolver", return_value=solver),
        pytest.raises(AuthenticationFailedError, match="操作过于频繁"),
    ):
        service.ensure_authenticated(
            username="test-credit-code",
            mobile="test-mobile",
            password="test-password",
        )

    assert updates == [
        "自动验证：验证码操作过于频繁，请等待 1 小时后再试"
    ]
    service._wait_for_timeout.assert_not_called()


def test_disabled_captcha_keeps_manual_verification_wait(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    settings = replace(
        settings,
        captcha=replace(settings.captcha, enabled=False),
        browser=replace(settings.browser, manual_login_timeout_seconds=0),
    )
    page = SimpleNamespace(url=settings.site.login_url)
    updates: list[str] = []
    service = LoginService(  # type: ignore[arg-type]
        page,
        settings,
        progress_callback=updates.append,
    )
    service._open_login_entry = Mock()  # type: ignore[method-assign]
    service.is_authenticated = Mock(return_value=False)  # type: ignore[method-assign]
    service._autofill_and_submit = Mock(return_value=True)  # type: ignore[method-assign]

    with pytest.raises(AuthenticationFailedError, match="等待人工登录超时"):
        service.ensure_authenticated(
            username="test-credit-code",
            mobile="test-mobile",
            password="test-password",
        )

    assert updates == [
        "人工验证：验证码自动验证未启用，请在浏览器中完成安全验证"
    ]
