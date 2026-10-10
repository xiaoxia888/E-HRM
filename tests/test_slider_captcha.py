from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import cv2
import numpy as np
import pytest

from ehrm.browser.captcha import CaptchaAutomationError, CaptchaSolver
from ehrm.browser.slider_captcha import (
    YidunSliderSolver,
    locate_jigsaw_gap,
    normalize_piece_to_background,
    parse_yidun_check,
)
from ehrm.core.settings import load_settings


def test_locate_jigsaw_gap_uses_masked_texture_not_first_similar_color() -> None:
    rng = np.random.default_rng(2026)
    background = rng.integers(10, 245, (90, 240, 3), dtype=np.uint8)
    offset = 112
    piece = np.zeros((90, 48, 4), dtype=np.uint8)
    piece[18:70, 5:43, :3] = background[18:70, offset + 5:offset + 43]
    piece[18:70, 5:43, 3] = 255

    assert locate_jigsaw_gap(background, piece) == (offset, 0)


def test_locate_cropped_jigsaw_piece_at_rendered_vertical_position() -> None:
    rng = np.random.default_rng(2027)
    background = rng.integers(10, 245, (90, 240, 3), dtype=np.uint8)
    x, y = 112, 22
    piece = np.zeros((50, 48, 4), dtype=np.uint8)
    piece[5:45, 5:43, :3] = background[y + 5:y + 45, x + 5:x + 43]
    piece[5:45, 5:43, 3] = 255

    assert locate_jigsaw_gap(
        background, piece, expected_y=y, y_tolerance=2
    ) == (x, y)


def test_normalize_piece_uses_rendered_size_not_original_height() -> None:
    background = np.zeros((320, 640, 3), dtype=np.uint8)
    piece = np.zeros((60, 46, 4), dtype=np.uint8)
    normalized = normalize_piece_to_background(
        background,
        piece,
        {"width": 320.0, "height": 160.0},
        {"width": 46.0, "height": 60.0},
    )

    assert normalized.shape == (120, 92, 4)


def test_normalize_piece_with_observed_yidun_image_sizes() -> None:
    background = np.zeros((160, 320, 3), dtype=np.uint8)
    piece = np.zeros((158, 60, 4), dtype=np.uint8)

    normalized = normalize_piece_to_background(
        background,
        piece,
        {"width": 320.0, "height": 160.0},
        {"width": 61.0, "height": 160.0},
    )

    assert normalized.shape == (160, 61, 4)


def test_locate_featureless_piece_by_its_outline() -> None:
    background = np.full((160, 320, 3), 80, dtype=np.uint8)
    piece = np.zeros((160, 61, 4), dtype=np.uint8)
    alpha = np.zeros((160, 61), dtype=np.uint8)
    cv2.rectangle(alpha, (12, 20), (46, 70), 255, -1)
    cv2.circle(alpha, (46, 45), 10, 255, -1)
    piece[:, :, :3] = 255
    piece[:, :, 3] = alpha
    outline = cv2.Canny(alpha, 60, 160)
    background[:, 184:245][outline > 0] = 255
    background[80:160, 67:128][outline[:80] > 0] = 255

    gap_x, gap_y = locate_jigsaw_gap(
        background, piece, expected_y=0, y_tolerance=2
    )

    assert abs(gap_x - 184) <= 2
    assert gap_y == 0


def test_locate_jigsaw_gap_rejects_ambiguous_image() -> None:
    background = np.full((90, 240, 3), 100, dtype=np.uint8)
    piece = np.zeros((90, 48, 4), dtype=np.uint8)
    piece[18:70, 5:43, :3] = 100
    piece[18:70, 5:43, 3] = 255

    with pytest.raises(CaptchaAutomationError, match="分数无效|不确定"):
        locate_jigsaw_gap(background, piece)


def test_drag_calibrates_actual_piece_travel_before_releasing() -> None:
    state = {"pointer_distance": 0.0}
    start_x = 100.0
    piece_start_x = 475.5
    slider_start_x = 476.5
    actual_ratio = 232 / 242

    def move(x: float, _y: float, *, steps: int) -> None:
        assert steps > 0
        state["pointer_distance"] = x - start_x

    page = SimpleNamespace(
        mouse=SimpleNamespace(move=move), wait_for_timeout=Mock()
    )
    piece = SimpleNamespace(
        bounding_box=lambda: {
            "x": piece_start_x + state["pointer_distance"] * actual_ratio
        }
    )
    slider = SimpleNamespace(
        bounding_box=lambda: {
            "x": slider_start_x + state["pointer_distance"]
        }
    )
    solver = YidunSliderSolver(page, Mock(), Mock(), pacer=Mock())

    alignment_error = solver._drag_piece_to_target(
        piece,
        slider,
        start_x=start_x,
        start_y=50.0,
        piece_start_x=piece_start_x,
        slider_start_x=slider_start_x,
        target_x=piece_start_x + 242,
        max_distance=279,
    )

    assert state["pointer_distance"] > 242
    assert abs(state["pointer_distance"] * actual_ratio - 242) <= 2
    assert abs(alignment_error) <= 2


def test_drag_calibrates_fixed_offset_in_piece_travel() -> None:
    state = {"pointer_distance": 0.0}
    start_x = 100.0
    piece_start_x = 475.5

    def move(x: float, _y: float, *, steps: int) -> None:
        assert steps > 0
        state["pointer_distance"] = x - start_x

    page = SimpleNamespace(
        mouse=SimpleNamespace(move=move), wait_for_timeout=Mock()
    )
    piece = SimpleNamespace(
        bounding_box=lambda: {
            "x": piece_start_x + max(0, state["pointer_distance"] - 10)
        }
    )
    slider = SimpleNamespace(
        bounding_box=lambda: {"x": 476.5 + state["pointer_distance"]}
    )
    solver = YidunSliderSolver(page, Mock(), Mock(), pacer=Mock())

    alignment_error = solver._drag_piece_to_target(
        piece,
        slider,
        start_x=start_x,
        start_y=50.0,
        piece_start_x=piece_start_x,
        slider_start_x=476.5,
        target_x=piece_start_x + 242,
        max_distance=279,
    )

    assert state["pointer_distance"] == pytest.approx(252)
    assert abs(alignment_error) <= 2


def test_drag_stops_if_piece_does_not_move() -> None:
    page = SimpleNamespace(mouse=SimpleNamespace(move=Mock()), wait_for_timeout=Mock())
    piece = SimpleNamespace(bounding_box=lambda: {"x": 475.5})
    slider = SimpleNamespace(bounding_box=lambda: {"x": 476.5})
    solver = YidunSliderSolver(page, Mock(), Mock(), pacer=Mock())

    with pytest.raises(CaptchaAutomationError, match="未按预期移动"):
        solver._drag_piece_to_target(
            piece,
            slider,
            start_x=100.0,
            start_y=50.0,
            piece_start_x=475.5,
            slider_start_x=476.5,
            target_x=717.5,
            max_distance=279,
        )


def test_parse_yidun_check_requires_explicit_success() -> None:
    assert parse_yidun_check('callback({"error":0,"data":{"result":true}});')
    assert not parse_yidun_check('{"error":0,"data":{"result":false}}')
    with pytest.raises(CaptchaAutomationError, match="缺少明确结果"):
        parse_yidun_check('{"error":0,"data":{"token":"secret"}}')


def test_solver_routes_visible_yidun_widget_to_slider() -> None:
    settings = load_settings(Path("config/settings.toml"))
    slider = SimpleNamespace(count=Mock(return_value=1), is_visible=Mock(return_value=True))
    frame = SimpleNamespace(locator=Mock(return_value=SimpleNamespace(first=slider)))
    page = SimpleNamespace(
        url=settings.site.login_url,
        frames=[frame],
        wait_for_timeout=Mock(),
    )
    pacer = Mock()
    solver = CaptchaSolver(page, settings.captcha, pacer=pacer)  # type: ignore[arg-type]
    slider_solver = Mock()
    slider_solver.solve.return_value = True

    with patch(
        "ehrm.browser.slider_captcha.YidunSliderSolver", return_value=slider_solver
    ) as solver_type:
        assert solver.solve() is True

    solver_type.assert_called_once()
    slider_solver.solve.assert_called_once_with()


def test_yidun_puzzle_wins_over_earlier_tencent_drag_shell() -> None:
    settings = load_settings(Path("config/settings.toml"))

    def frame_with(*visible_selectors: str) -> SimpleNamespace:
        def locator(selector: str) -> SimpleNamespace:
            visible = selector in visible_selectors
            element = SimpleNamespace(
                count=lambda: int(visible), is_visible=lambda: visible
            )
            return SimpleNamespace(first=element)

        return SimpleNamespace(locator=locator)

    drag_shell = frame_with("#tcWrap.tc-drag")
    puzzle = frame_with(".yidun_modal .yidun--jigsaw")
    page = SimpleNamespace(
        url=settings.site.login_url,
        frames=[drag_shell, puzzle],
        wait_for_timeout=Mock(),
    )
    solver = CaptchaSolver(page, settings.captcha, pacer=Mock())  # type: ignore[arg-type]

    assert solver._wait_for_challenge_kind() == ("yidun", puzzle)


def test_legacy_click_requires_its_images_not_just_tencent_shell() -> None:
    settings = load_settings(Path("config/settings.toml"))
    settings = replace(settings, captcha=replace(settings.captcha, frame_timeout_ms=50))
    visible = SimpleNamespace(count=lambda: 1, is_visible=lambda: True)
    missing = SimpleNamespace(count=lambda: 0, is_visible=lambda: False)

    def locator(selector: str) -> SimpleNamespace:
        return SimpleNamespace(
            first=visible if selector == "#tcWrap.tc-drag" else missing
        )

    page = SimpleNamespace(
        url=settings.site.login_url,
        frames=[SimpleNamespace(locator=locator)],
        wait_for_timeout=Mock(),
    )
    solver = CaptchaSolver(page, settings.captcha, pacer=Mock())  # type: ignore[arg-type]

    with pytest.raises(CaptchaAutomationError, match="拖动验证码外壳"):
        solver._wait_for_challenge_kind()


def test_unknown_visible_verification_returns_actionable_error() -> None:
    settings = load_settings(Path("config/settings.toml"))
    settings = replace(settings, captcha=replace(settings.captcha, frame_timeout_ms=50))
    visible = SimpleNamespace(count=lambda: 1, is_visible=lambda: True)
    missing = SimpleNamespace(count=lambda: 0, is_visible=lambda: False)
    frame = SimpleNamespace(
        locator=lambda selector: SimpleNamespace(
            first=visible if selector == ".yidun_modal" else missing
        )
    )
    page = SimpleNamespace(
        url=settings.site.login_url,
        frames=[frame],
        wait_for_timeout=Mock(),
    )
    solver = CaptchaSolver(page, settings.captcha, pacer=Mock())  # type: ignore[arg-type]

    with pytest.raises(CaptchaAutomationError, match="未识别的安全验证方式"):
        solver.solve()


def test_yidun_rejection_stops_after_at_most_three_attempts() -> None:
    settings = load_settings(Path("config/settings.toml"))
    settings = replace(settings.captcha, max_attempts=5)
    box = {"x": 100.0, "y": 100.0, "width": 320.0, "height": 160.0}
    slider_box = {"x": 100.0, "y": 275.0, "width": 40.0, "height": 40.0}
    control_box = {"x": 100.0, "y": 275.0, "width": 320.0, "height": 40.0}
    background = SimpleNamespace(
        wait_for=Mock(), get_attribute=lambda _name: "https://example.test/bg",
        bounding_box=lambda: box,
    )
    piece = SimpleNamespace(
        wait_for=Mock(), get_attribute=lambda _name: "https://example.test/piece",
        bounding_box=lambda: {**box, "width": 60.0},
    )
    slider = SimpleNamespace(wait_for=Mock(), bounding_box=lambda: slider_box)
    control = SimpleNamespace(bounding_box=lambda: control_box)
    widget = SimpleNamespace(
        wait_for=Mock(),
        locator=lambda selector: SimpleNamespace(
            first={
                ".yidun_bg-img": background,
                ".yidun_jigsaw": piece,
                ".yidun_slider": slider,
                ".yidun_control": control,
            }[selector]
        ),
    )
    frame = SimpleNamespace(locator=lambda _selector: SimpleNamespace(first=widget))
    response_info = MagicMock()
    response_info.__enter__.return_value.value.text.return_value = (
        '{"error":0,"data":{"result":false}}'
    )
    page = SimpleNamespace(
        mouse=SimpleNamespace(move=Mock(), down=Mock(), up=Mock()),
        expect_response=Mock(return_value=response_info),
    )
    solver = YidunSliderSolver(page, frame, settings, pacer=Mock())  # type: ignore[arg-type]
    solver._read_image = Mock(return_value=np.zeros((160, 320, 3), dtype=np.uint8))  # type: ignore[method-assign]
    solver._drag_piece_to_target = Mock(return_value=0.0)  # type: ignore[method-assign]
    solver._wait_for_new_image = Mock()  # type: ignore[method-assign]

    with (
        patch("ehrm.browser.slider_captcha.normalize_piece_to_background", return_value=Mock()),
        patch("ehrm.browser.slider_captcha.locate_jigsaw_gap", return_value=(100, 0)),
        pytest.raises(CaptchaAutomationError, match="连续 3 次未通过"),
    ):
        solver.solve()

    assert page.expect_response.call_count == 3
    assert solver._wait_for_new_image.call_count == 2
