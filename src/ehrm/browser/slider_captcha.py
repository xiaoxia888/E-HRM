"""NetEase Yidun jigsaw support for the JSHRSS unit login page.

The page's own SDK still creates and sends the verification payload. This
module only finds the visible puzzle position and operates the slider; it
never constructs a verification request or treats a moved slider as success.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import cv2
import numpy as np
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, Locator, Page, Response

from ehrm.browser.captcha import (
    CaptchaAutomationError,
    _MAX_AUTOMATED_ATTEMPTS,
)
from ehrm.browser.captcha_policy import is_allowed_host_url
from ehrm.browser.interaction_pacer import BrowserInteractionPacer
from ehrm.core.settings import CaptchaSettings


_LOGGER = logging.getLogger("ehrm")
_IMAGE_HOST = "necaptcha.nosdn.127.net"
_CHECK_HOST = "c.dun.163.com"
_CHECK_PATH = "/api/v3/check"
_JIGSAW = ".yidun_modal .yidun--jigsaw"


def locate_jigsaw_gap(
    background: np.ndarray,
    piece: np.ndarray,
    *,
    expected_y: int | None = None,
    y_tolerance: int = 0,
) -> tuple[int, int]:
    """Return the puzzle's (left, top) in background-image pixels.

    Images must first be normalized to the same pixel density. The piece may
    cover the full canvas height or be a cropped transparent image. Masked edge
    matching avoids choosing a visually similar decoy solely by color.
    """
    if background.ndim != 3 or background.shape[2] != 3:
        raise CaptchaAutomationError("滑块背景图格式不正确")
    if piece.ndim != 3 or piece.shape[2] != 4:
        raise CaptchaAutomationError("滑块拼图缺少透明通道")
    if (
        background.shape[0] < piece.shape[0]
        or background.shape[1] <= piece.shape[1]
    ):
        raise CaptchaAutomationError("滑块图片尺寸不匹配")

    alpha_mask = (piece[:, :, 3] >= 128).astype(np.uint8)
    mask = cv2.erode(alpha_mask, np.ones((5, 5), np.uint8))
    if cv2.countNonZero(mask) < 100:
        raise CaptchaAutomationError("滑块拼图有效区域过小")

    source_edges = cv2.Canny(background, 60, 160)
    outline_location: tuple[int, int] | None = None
    outline_edges = cv2.Canny(alpha_mask * 255, 60, 160)
    if cv2.countNonZero(outline_edges) >= 30:
        outline_scores = cv2.matchTemplate(
            source_edges, outline_edges, cv2.TM_CCORR_NORMED
        )
        if np.isfinite(outline_scores).all():
            outline_candidates = outline_scores.copy()
            if expected_y is not None:
                if not 0 <= expected_y < outline_candidates.shape[0]:
                    raise CaptchaAutomationError("滑块显示位置超出背景图片范围")
                top = max(0, expected_y - y_tolerance)
                bottom = min(outline_candidates.shape[0], expected_y + y_tolerance + 1)
                outline_candidates[:top, :] = -1
                outline_candidates[bottom:, :] = -1
            outline_y, outline_x = (int(value) for value in np.unravel_index(
                int(np.argmax(outline_candidates)), outline_candidates.shape
            ))
            outline_best = float(outline_candidates[outline_y, outline_x])
            other_outlines = outline_candidates.copy()
            exclude_x = max(20, piece.shape[1] // 2)
            exclude_y = max(10, piece.shape[0] // 2)
            other_outlines[
                max(0, outline_y - exclude_y):outline_y + exclude_y + 1,
                max(0, outline_x - exclude_x):outline_x + exclude_x + 1,
            ] = -1
            outline_second = float(np.max(other_outlines))
            _LOGGER.info(
                "滑块轮廓匹配：边缘 %.3f、次选 %.3f、位置 (%d,%d)",
                outline_best, outline_second, outline_x, outline_y,
            )
            if outline_best >= 0.13 and outline_best - outline_second >= 0.05:
                outline_location = (outline_x, outline_y)

    piece_edges = cv2.Canny(piece[:, :, :3], 60, 160)
    edge_scores = cv2.matchTemplate(
        source_edges, piece_edges, cv2.TM_CCORR_NORMED, mask=mask
    )
    color_scores = cv2.matchTemplate(
        background, piece[:, :, :3], cv2.TM_CCORR_NORMED, mask=mask
    )
    if not np.isfinite(edge_scores).all() or not np.isfinite(color_scores).all():
        if outline_location is not None:
            return outline_location
        raise CaptchaAutomationError("滑块图片匹配分数无效")

    candidates = edge_scores.copy()
    if expected_y is not None:
        if not 0 <= expected_y < candidates.shape[0]:
            raise CaptchaAutomationError("滑块显示位置超出背景图片范围")
        top = max(0, expected_y - y_tolerance)
        bottom = min(candidates.shape[0], expected_y + y_tolerance + 1)
        candidates[:top, :] = -1
        candidates[bottom:, :] = -1
    best_y, best_x = (int(value) for value in np.unravel_index(
        int(np.argmax(candidates)), candidates.shape
    ))
    best_edge = float(candidates[best_y, best_x])
    best_color = float(color_scores[best_y, best_x])
    other = candidates.copy()
    exclude_x = max(20, piece.shape[1] // 2)
    exclude_y = max(10, piece.shape[0] // 2)
    other[
        max(0, best_y - exclude_y):best_y + exclude_y + 1,
        max(0, best_x - exclude_x):best_x + exclude_x + 1,
    ] = -1
    second_edge = float(np.max(other))
    _LOGGER.info(
        "滑块图片匹配：边缘 %.3f、次选 %.3f、颜色 %.3f",
        best_edge, second_edge, best_color,
    )
    texture_confident = (
        best_edge >= 0.45
        and best_edge - second_edge >= 0.12
        and best_color >= 0.80
    )
    if texture_confident:
        if outline_location is not None and (
            abs(best_x - outline_location[0]) > 4
            or abs(best_y - outline_location[1]) > 4
        ):
            raise CaptchaAutomationError(
                "拼图纹理与缺口轮廓定位冲突，已停止自动拖动"
            )
        return best_x, best_y
    if outline_location is not None:
        return outline_location
    raise CaptchaAutomationError("滑块缺口识别不确定，已停止自动拖动")


def normalize_piece_to_background(
    background: np.ndarray,
    piece: np.ndarray,
    background_box: dict[str, float],
    piece_box: dict[str, float],
) -> np.ndarray:
    """Use rendered CSS sizes to reconcile differently scaled image files."""
    bg_width = float(background_box["width"])
    bg_height = float(background_box["height"])
    piece_width = float(piece_box["width"])
    piece_height = float(piece_box["height"])
    if min(bg_width, bg_height, piece_width, piece_height) <= 0:
        raise CaptchaAutomationError("滑块图片显示尺寸无效")
    width = round(piece_width * background.shape[1] / bg_width)
    height = round(piece_height * background.shape[0] / bg_height)
    if width < 1 or height < 1 or width >= background.shape[1] or height > background.shape[0]:
        raise CaptchaAutomationError(
            "滑块图片显示比例不匹配"
            f"（背景 {background.shape[1]}×{background.shape[0]}，"
            f"拼图 {piece.shape[1]}×{piece.shape[0]}，"
            f"目标 {width}×{height}）"
        )
    if (width, height) == (piece.shape[1], piece.shape[0]):
        return piece
    return cv2.resize(piece, (width, height), interpolation=cv2.INTER_LINEAR)


def parse_yidun_check(body: str) -> bool:
    """Read a JSON or JSONP check response without exposing its token."""
    text = body.strip()
    if not text.startswith("{"):
        opening = text.find("(")
        closing = text.rfind(")")
        if opening < 1 or closing <= opening:
            raise CaptchaAutomationError("滑块校验响应格式不正确")
        text = text[opening + 1:closing]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CaptchaAutomationError("滑块校验响应不是有效 JSON") from exc
    if not isinstance(payload, dict) or payload.get("error") != 0:
        raise CaptchaAutomationError("滑块校验服务返回错误")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("result"), bool):
        raise CaptchaAutomationError("滑块校验响应缺少明确结果")
    return data["result"]


class YidunSliderSolver:
    def __init__(
        self,
        page: Page,
        frame: Frame,
        settings: CaptchaSettings,
        *,
        pacer: BrowserInteractionPacer,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.page = page
        self.frame = frame
        self.settings = settings
        self.pacer = pacer
        self._progress_callback = progress_callback

    def solve(self) -> bool:
        self._progress("自动验证：检测到拼图滑块，正在识别缺口")
        max_attempts = min(self.settings.max_attempts, _MAX_AUTOMATED_ATTEMPTS)
        for attempt in range(1, max_attempts + 1):
            widget = self.frame.locator(_JIGSAW).first
            widget.wait_for(state="visible", timeout=self.settings.frame_timeout_ms)
            background = widget.locator(".yidun_bg-img").first
            piece = widget.locator(".yidun_jigsaw").first
            slider = widget.locator(".yidun_slider").first
            for element in (background, piece, slider):
                element.wait_for(state="visible", timeout=self.settings.frame_timeout_ms)
            bg_url = background.get_attribute("src") or ""
            piece_url = piece.get_attribute("src") or ""
            bg_image = self._read_image(bg_url, cv2.IMREAD_COLOR)
            piece_image = self._read_image(piece_url, cv2.IMREAD_UNCHANGED)
            bg_box = background.bounding_box()
            piece_box = piece.bounding_box()
            slider_box = slider.bounding_box()
            control_box = widget.locator(".yidun_control").first.bounding_box()
            if (
                bg_box is None or piece_box is None
                or slider_box is None or control_box is None
            ):
                raise CaptchaAutomationError("无法读取滑块元素位置")
            normalized_piece = normalize_piece_to_background(
                bg_image, piece_image, bg_box, piece_box
            )
            expected_y = round(
                (piece_box["y"] - bg_box["y"])
                * bg_image.shape[0] / bg_box["height"]
            )
            gap_x, _ = locate_jigsaw_gap(
                bg_image,
                normalized_piece,
                expected_y=expected_y,
                y_tolerance=max(2, round(bg_image.shape[0] * 0.02)),
            )
            target_x = bg_box["x"] + gap_x * bg_box["width"] / bg_image.shape[1]
            distance = target_x - piece_box["x"]
            max_distance = (
                control_box["x"] + control_box["width"]
                - slider_box["x"] - slider_box["width"]
            )
            _LOGGER.info(
                "滑块落点：图片缺口 x=%d，页面目标 x=%.1f，拼图起点 x=%.1f，"
                "计划拖动 %.1f，最大可拖动 %.1f",
                gap_x, target_x, piece_box["x"], distance, max_distance,
            )
            if distance <= 0 or distance > max_distance + 2:
                raise CaptchaAutomationError("滑块缺口位置超出可拖动范围")
            self._progress(
                f"自动验证：第 {attempt}/{max_attempts} 次拖动滑块"
            )
            x = slider_box["x"] + slider_box["width"] / 2
            y = slider_box["y"] + slider_box["height"] / 2
            try:
                with self.page.expect_response(
                    self._is_check_response,
                    timeout=self.settings.verify_timeout_ms,
                ) as response_info:
                    self.pacer.wait_before_action()
                    self.page.mouse.move(x, y)
                    self.page.mouse.down()
                    try:
                        alignment_error = self._drag_piece_to_target(
                            piece,
                            slider,
                            start_x=x,
                            start_y=y,
                            piece_start_x=piece_box["x"],
                            slider_start_x=slider_box["x"],
                            target_x=target_x,
                            max_distance=max_distance,
                        )
                        self._progress(
                            f"自动验证：拼图落点偏差 {abs(alignment_error):.1f} 像素"
                        )
                    finally:
                        self.page.mouse.up()
                passed = parse_yidun_check(response_info.value.text())
            except PlaywrightError as exc:
                raise CaptchaAutomationError("等待滑块校验响应超时或拖动失败") from exc
            if passed:
                self._progress("自动验证：滑块校验通过，正在等待登录结果")
                return True
            _LOGGER.warning("滑块已拖动到识别位置，但验证码服务返回未通过")
            if attempt == max_attempts:
                break
            self._progress("自动验证：滑块未通过，正在等待新拼图")
            self._wait_for_new_image(bg_url, widget)
        raise CaptchaAutomationError(
            f"滑块验证码连续 {max_attempts} 次未通过，已停止自动登录"
        )

    def _drag_piece_to_target(
        self,
        piece: Locator,
        slider: Locator,
        *,
        start_x: float,
        start_y: float,
        piece_start_x: float,
        slider_start_x: float,
        target_x: float,
        max_distance: float,
    ) -> float:
        """Calibrate pointer travel against the puzzle's actual DOM movement."""
        piece_distance = target_x - piece_start_x
        first_probe = min(piece_distance * 0.2, 40.0)
        second_probe = min(piece_distance * 0.4, 80.0)
        if first_probe < 6 or second_probe - first_probe < 6:
            raise CaptchaAutomationError("滑块目标距离过短，无法可靠校准")
        self.page.mouse.move(start_x + first_probe, start_y, steps=6)
        self.page.wait_for_timeout(80)
        first_piece = piece.bounding_box()
        if first_piece is None:
            raise CaptchaAutomationError("拖动中无法读取拼图位置")
        first_moved = first_piece["x"] - piece_start_x
        self.page.mouse.move(start_x + second_probe, start_y, steps=6)
        self.page.wait_for_timeout(80)
        second_piece = piece.bounding_box()
        probe_slider = slider.bounding_box()
        if second_piece is None or probe_slider is None:
            raise CaptchaAutomationError("拖动中无法读取拼图或滑块位置")
        second_moved = second_piece["x"] - piece_start_x
        slider_moved = probe_slider["x"] - slider_start_x
        if slider_moved < 5 or second_moved - first_moved < 3:
            raise CaptchaAutomationError("拖动时拼图未按预期移动，无法继续校准")
        ratio = (second_moved - first_moved) / (second_probe - first_probe)
        if not 0.5 <= ratio <= 1.5:
            raise CaptchaAutomationError("滑块与拼图移动比例异常，无法继续校准")
        _LOGGER.info(
            "滑块校准：鼠标移动 %.1f/%.1f，滑块移动 %.1f，"
            "拼图移动 %.1f/%.1f，局部比例 %.3f",
            first_probe, second_probe, slider_moved,
            first_moved, second_moved, ratio,
        )

        pointer_distance = second_probe + (piece_distance - second_moved) / ratio
        if not 0 < pointer_distance <= max_distance + 2:
            raise CaptchaAutomationError("校准后的目标超出滑块可拖动范围")
        self.page.mouse.move(start_x + pointer_distance, start_y, steps=20)
        self.page.wait_for_timeout(80)
        final_piece = piece.bounding_box()
        if final_piece is None:
            raise CaptchaAutomationError("拖动后无法读取拼图位置")
        error = target_x - final_piece["x"]
        if abs(error) > 1.5:
            if abs(error) > 20:
                raise CaptchaAutomationError("拼图落点偏差过大，无法继续校准")
            pointer_distance += error / ratio
            if not 0 < pointer_distance <= max_distance + 2:
                raise CaptchaAutomationError("拼图修正位置超出滑块可拖动范围")
            self.page.mouse.move(start_x + pointer_distance, start_y, steps=6)
            self.page.wait_for_timeout(80)
            final_piece = piece.bounding_box()
            if final_piece is None:
                raise CaptchaAutomationError("修正后无法读取拼图位置")
            error = target_x - final_piece["x"]
        _LOGGER.info(
            "滑块最终落点：目标 x=%.1f，拼图实际 x=%.1f，偏差 %.1f",
            target_x, final_piece["x"], error,
        )
        if abs(error) > 2:
            raise CaptchaAutomationError("拼图落点仍未对齐，无法继续校准")
        return error

    def _read_image(self, url: str, mode: int) -> np.ndarray:
        if not is_allowed_host_url(url, self.settings.allowed_hosts) or (
            urlsplit(url).hostname or ""
        ).lower() != _IMAGE_HOST:
            raise CaptchaAutomationError("滑块图片主机不在允许列表中")
        response = self.page.request.get(url, timeout=self.settings.frame_timeout_ms)
        if not response.ok:
            raise CaptchaAutomationError("滑块图片下载失败")
        image = cv2.imdecode(np.frombuffer(response.body(), np.uint8), mode)
        if image is None:
            raise CaptchaAutomationError("滑块图片解码失败")
        return image

    def _is_check_response(self, response: Response) -> bool:
        parsed = urlsplit(response.url)
        return (
            parsed.path == _CHECK_PATH
            and parsed.hostname == _CHECK_HOST
            and is_allowed_host_url(response.url, self.settings.allowed_hosts)
        )

    def _wait_for_new_image(self, previous_url: str, widget: Locator) -> None:
        deadline = time.monotonic() + self.settings.image_change_timeout_ms / 1000.0
        while time.monotonic() < deadline:
            current = widget.locator(".yidun_bg-img").first.get_attribute("src")
            if current and current != previous_url:
                return
            self.page.wait_for_timeout(200)
        raise CaptchaAutomationError("滑块失败后未加载新拼图，已停止重试")

    def _progress(self, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(message)
