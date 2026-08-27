from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import numpy as np
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, Locator, Page, Response

from ehrm.browser.captcha_matcher import (
    CaptchaMatch,
    captcha_debug_images,
    match_captcha_symbols,
    render_captcha_matches,
)
from ehrm.browser.captcha_policy import (
    is_allowed_host_url,
    url_without_sensitive_query,
)
from ehrm.core.settings import CaptchaSettings


_LOGGER = logging.getLogger("ehrm")
_BACKGROUND_URL_PATTERN = re.compile(r'^url\(["\']?(.*?)["\']?\)$')
_VERIFY_SUCCESS_CODE = "0"
_VERIFY_RETRY_CODE = "50"
_VERIFY_RATE_LIMIT_CODE = "12"
_CLICK_BOUNDARY_MARGIN_PX = 1.0


class CaptchaAutomationError(RuntimeError):
    pass


class CaptchaRateLimitedError(CaptchaAutomationError):
    """The verification service rejected additional attempts as too frequent."""

    pass


@dataclass(frozen=True, slots=True)
class _Challenge:
    frame: Frame
    target: Locator
    background: Locator
    target_url: str
    background_url: str
    target_image: np.ndarray
    background_image: np.ndarray


@dataclass(frozen=True, slots=True)
class _ClickPoint:
    sequence: int
    image_x: int
    image_y: int


def image_point_to_page(
    *,
    image_point: tuple[int, int],
    image_size: tuple[int, int],
    element_box: dict[str, float],
) -> tuple[float, float]:
    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        raise ValueError("验证码背景图片尺寸无效")
    x, y = image_point
    return (
        float(element_box["x"]) + x * float(element_box["width"]) / image_width,
        float(element_box["y"]) + y * float(element_box["height"]) / image_height,
    )


class CaptchaSolver:
    """Solves click challenges only for explicitly configured test hosts."""

    def __init__(
        self,
        page: Page,
        settings: CaptchaSettings,
        *,
        delay_sampler: Callable[[int, int], int] | None = None,
        offset_sampler: Callable[[int, int], int] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.page = page
        self.settings = settings
        generator = random.SystemRandom()
        self._delay_sampler = delay_sampler or generator.randint
        self._offset_sampler = offset_sampler or generator.randint
        self._progress_callback = progress_callback
        self._diagnostic_run_dir: Path | None = None

    def is_supported_page(self) -> bool:
        return is_allowed_host_url(
            self.page.url, self.settings.allowed_hosts
        )

    def solve(self) -> bool:
        if not self.settings.enabled:
            return False
        if not self.is_supported_page():
            raise CaptchaAutomationError(
                "当前页面主机不在 rights_statement.captcha.allowed_hosts 中"
            )

        previous_sources: tuple[str, str] | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            self._progress(
                f"自动验证：正在等待验证码加载（第 {attempt}/"
                f"{self.settings.max_attempts} 次），请勿手动点击"
            )
            frame = self._find_frame()
            if previous_sources is not None:
                self._wait_for_source_change(frame, previous_sources)
                frame = self._find_frame()
            challenge = self._load_challenge(frame)
            diagnostic_dir = self._save_diagnostic_sources(
                challenge,
                attempt,
            )
            self._progress(
                f"自动验证：验证码已加载，正在识别图形符号（第 {attempt}/"
                f"{self.settings.max_attempts} 次）"
            )
            recognition_started = time.monotonic()
            try:
                matches = match_captcha_symbols(
                    challenge.target_image,
                    challenge.background_image,
                    progress_callback=lambda completed, total: self._progress(
                        f"自动验证：图形符号识别进度 {completed}/{total}"
                    ),
                )
            except (ValueError, cv2.error) as exc:
                self._save_diagnostic_result(
                    diagnostic_dir,
                    challenge.background_image,
                    [],
                )
                raise CaptchaAutomationError(
                    f"验证码图片识别失败：{exc}"
                ) from exc
            recognition_seconds = time.monotonic() - recognition_started
            _LOGGER.info(
                "验证码第 %d 次识别耗时 %.3fs: %s",
                attempt,
                recognition_seconds,
                ", ".join(
                    f"{match.index}={match.score:.4f}" for match in matches
                ),
            )
            self._progress(
                f"自动验证：识别完成（{recognition_seconds:.2f} 秒），"
                f"正在按顺序点击 {len(matches)} 个符号"
            )
            click_points = self._click_matches(challenge, matches)
            self._save_diagnostic_result(
                diagnostic_dir,
                challenge.background_image,
                click_points,
                matches=matches,
            )
            self._progress("自动验证：符号点击完成，正在提交验证码")
            result = self._confirm_and_wait(challenge.frame)
            error_code = str(result.get("errorCode", ""))
            if error_code == _VERIFY_SUCCESS_CODE:
                return True
            if error_code == _VERIFY_RATE_LIMIT_CODE:
                raise CaptchaRateLimitedError(
                    "验证码操作过于频繁（errorCode=12），"
                    "请等待 1 小时后再试"
                )
            if error_code != _VERIFY_RETRY_CODE:
                message = str(result.get("errMessage", "")).strip()
                raise CaptchaAutomationError(
                    f"验证码返回未知结果 errorCode={error_code}"
                    + (f"，{message}" if message else "")
                )
            self._progress("自动验证：本次未通过，正在加载下一组验证码")
            previous_sources = (
                challenge.target_url,
                challenge.background_url,
            )

        raise CaptchaAutomationError(
            f"验证码连续 {self.settings.max_attempts} 次验证失败"
        )

    def _find_frame(self) -> Frame:
        deadline = time.monotonic() + self.settings.frame_timeout_ms / 1000.0
        while time.monotonic() < deadline:
            for frame in self.page.frames:
                try:
                    root = frame.locator("#tcWrap").first
                    if root.count() > 0 and root.is_visible():
                        self._report_frame_features(frame)
                        return frame
                except PlaywrightError:
                    continue
            self.page.wait_for_timeout(100)
        raise CaptchaAutomationError("等待验证码 iframe 超时")

    def _report_frame_features(self, frame: Frame) -> None:
        try:
            webdriver = frame.evaluate("navigator.webdriver")
        except PlaywrightError:
            _LOGGER.debug("读取验证码 iframe 浏览器特征失败", exc_info=True)
            return
        frame_allowed = is_allowed_host_url(
            frame.url, self.settings.allowed_hosts
        )
        top_allowed = is_allowed_host_url(
            self.page.url, self.settings.allowed_hosts
        )
        scope = frame_allowed or top_allowed
        message = (
            "浏览器特征：验证码 iframe URL="
            f"{url_without_sensitive_query(frame.url)}，"
            f"stealth注入范围={'命中' if scope else '未命中'}，"
            f"navigator.webdriver={str(webdriver).lower()}"
        )
        _LOGGER.info(message)
        self._progress(message)

    def _load_challenge(self, frame: Frame) -> _Challenge:
        target = frame.locator(".tc-instruction-icon img").first
        background = frame.locator("#slideBg").first
        target.wait_for(state="visible", timeout=self.settings.frame_timeout_ms)
        background.wait_for(state="visible", timeout=self.settings.frame_timeout_ms)

        target_url = target.get_attribute("src") or ""
        background_url = self._background_url(background)
        resources_allowed = is_allowed_host_url(
            target_url, self.settings.allowed_hosts
        ) and is_allowed_host_url(
            background_url, self.settings.allowed_hosts
        )
        resource_message = (
            "验证码资源：目标图="
            f"{url_without_sensitive_query(target_url)}，背景图="
            f"{url_without_sensitive_query(background_url)}，"
            f"allowed_hosts={'命中' if resources_allowed else '未命中'}"
        )
        _LOGGER.info(resource_message)
        self._progress(resource_message)
        if not resources_allowed:
            raise CaptchaAutomationError(
                "验证码图片主机不在 allowed_hosts 中，已拒绝自动点击"
            )

        target_image = self._read_image(target, target_url)
        background_image = self._read_image(background, background_url)
        return _Challenge(
            frame=frame,
            target=target,
            background=background,
            target_url=target_url,
            background_url=background_url,
            target_image=target_image,
            background_image=background_image,
        )

    def _background_url(self, locator: Locator) -> str:
        value = locator.evaluate(
            "element => getComputedStyle(element).backgroundImage"
        )
        match = _BACKGROUND_URL_PATTERN.match(str(value).strip())
        if not match:
            raise CaptchaAutomationError("无法读取验证码背景图片地址")
        return match.group(1)

    def _read_image(self, locator: Locator, url: str) -> np.ndarray:
        payload: bytes | None = None
        try:
            response = self.page.request.get(
                url, timeout=self.settings.frame_timeout_ms
            )
            if response.ok:
                payload = response.body()
        except PlaywrightError as exc:
            _LOGGER.debug("读取验证码原图失败，改用元素截图: %s", exc)

        if payload is None:
            payload = locator.screenshot(
                timeout=self.settings.frame_timeout_ms,
                animations="disabled",
            )
        array = np.frombuffer(payload, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is None:
            raise CaptchaAutomationError("验证码图片解码失败")
        return image

    def _click_matches(
        self, challenge: _Challenge, matches: list[CaptchaMatch]
    ) -> list[_ClickPoint]:
        box = challenge.background.bounding_box()
        if box is None:
            raise CaptchaAutomationError("无法读取验证码背景元素坐标")
        image_height, image_width = challenge.background_image.shape[:2]
        click_points: list[_ClickPoint] = []

        for sequence, match in enumerate(
            sorted(matches, key=lambda item: item.index),
            start=1,
        ):
            page_x, page_y = image_point_to_page(
                image_point=match.center,
                image_size=(image_width, image_height),
                element_box=box,
            )
            x1, y1, x2, y2 = match.matched_bbox
            page_left, page_top = image_point_to_page(
                image_point=(x1, y1),
                image_size=(image_width, image_height),
                element_box=box,
            )
            page_right, page_bottom = image_point_to_page(
                image_point=(x2, y2),
                image_size=(image_width, image_height),
                element_box=box,
            )
            configured_offset = self.settings.click_offset_max_px
            left_room = max(
                0, int(page_x - page_left - _CLICK_BOUNDARY_MARGIN_PX)
            )
            right_room = max(
                0, int(page_right - page_x - _CLICK_BOUNDARY_MARGIN_PX)
            )
            top_room = max(
                0, int(page_y - page_top - _CLICK_BOUNDARY_MARGIN_PX)
            )
            bottom_room = max(
                0, int(page_bottom - page_y - _CLICK_BOUNDARY_MARGIN_PX)
            )
            offset_x = self._offset_sampler(
                -min(configured_offset, left_room),
                min(configured_offset, right_room),
            )
            offset_y = self._offset_sampler(
                -min(configured_offset, top_room),
                min(configured_offset, bottom_room),
            )
            page_x += offset_x
            page_y += offset_y
            _LOGGER.debug(
                "验证码符号 %d 点击偏移: x=%d, y=%d",
                match.index,
                offset_x,
                offset_y,
            )
            image_x = round(
                (page_x - float(box["x"]))
                * image_width
                / float(box["width"])
            )
            image_y = round(
                (page_y - float(box["y"]))
                * image_height
                / float(box["height"])
            )
            click_points.append(
                _ClickPoint(
                    sequence=sequence,
                    image_x=max(0, min(image_width - 1, image_x)),
                    image_y=max(0, min(image_height - 1, image_y)),
                )
            )
            self.page.mouse.click(page_x, page_y)
            self._random_pause()
        return click_points

    def _save_diagnostic_sources(
        self,
        challenge: _Challenge,
        attempt: int,
    ) -> Path | None:
        if not self.settings.diagnostic_images_enabled:
            return None
        try:
            if self._diagnostic_run_dir is None:
                run_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                self._diagnostic_run_dir = (
                    self.settings.diagnostic_output_dir / run_name
                )
            attempt_dir = self._diagnostic_run_dir / f"attempt_{attempt:02d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            self._write_png(attempt_dir / "1_target.png", challenge.target_image)
            self._write_png(
                attempt_dir / "2_background.png",
                challenge.background_image,
            )
        except (OSError, ValueError, cv2.error) as exc:
            _LOGGER.warning("保存验证码诊断原图失败: %s", exc)
            return None
        try:
            for filename, image in captcha_debug_images(
                challenge.target_image,
                challenge.background_image,
            ).items():
                self._write_png(attempt_dir / filename, image)
        except (OSError, ValueError, cv2.error) as exc:
            _LOGGER.warning("保存验证码算法中间图失败: %s", exc)
        return attempt_dir

    def _save_diagnostic_result(
        self,
        attempt_dir: Path | None,
        background_image: np.ndarray,
        click_points: list[_ClickPoint],
        *,
        matches: list[CaptchaMatch] | None = None,
    ) -> None:
        if attempt_dir is None:
            return
        try:
            result = background_image.copy()
            image_height, image_width = result.shape[:2]
            radius = max(12, round(min(image_width, image_height) * 0.04))
            font_scale = max(0.55, radius / 18.0)
            thickness = max(2, round(radius / 7))
            for point in click_points:
                center = (point.image_x, point.image_y)
                overlay = result.copy()
                cv2.circle(overlay, center, radius, (0, 140, 255), -1)
                cv2.addWeighted(overlay, 0.35, result, 0.65, 0, result)
                cv2.circle(result, center, radius, (255, 255, 255), thickness)
                cv2.circle(result, center, radius + thickness, (0, 140, 255), 2)
                label = str(point.sequence)
                (text_width, text_height), _ = cv2.getTextSize(
                    label,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale,
                    thickness,
                )
                origin = (
                    point.image_x - text_width // 2,
                    point.image_y + text_height // 2,
                )
                cv2.putText(
                    result,
                    label,
                    origin,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale,
                    (40, 40, 40),
                    thickness + 2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    result,
                    label,
                    origin,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale,
                    (255, 255, 255),
                    thickness,
                    cv2.LINE_AA,
                )
            destination = attempt_dir / "3_result.png"
            self._write_png(destination, result)
            if matches is not None:
                self._write_png(
                    attempt_dir / "13_selected_matches.png",
                    render_captcha_matches(background_image, matches),
                )
            message = f"验证码识别诊断图片已保存：{attempt_dir.resolve()}"
            _LOGGER.info(message)
            self._progress(message)
        except (OSError, ValueError, cv2.error) as exc:
            _LOGGER.warning("保存验证码诊断结果图失败: %s", exc)

    @staticmethod
    def _write_png(path: Path, image: np.ndarray) -> None:
        encoded, payload = cv2.imencode(".png", image)
        if not encoded:
            raise ValueError(f"PNG 编码失败：{path.name}")
        payload.tofile(path)

    def _confirm_and_wait(self, frame: Frame) -> dict[str, object]:
        confirm = frame.locator(".tc-action.verify-btn:visible").last
        confirm.wait_for(state="visible", timeout=self.settings.frame_timeout_ms)
        try:
            with self.page.expect_response(
                self._is_allowed_verify_response,
                timeout=self.settings.verify_timeout_ms,
            ) as response_info:
                confirm.click()
                self._random_pause()
            response = response_info.value
        except PlaywrightError as exc:
            raise CaptchaAutomationError("等待验证码校验响应超时") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise CaptchaAutomationError("验证码校验响应不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise CaptchaAutomationError("验证码校验响应不是 JSON 对象")
        return payload

    def _is_allowed_verify_response(self, response: Response) -> bool:
        parsed = urlsplit(response.url)
        return (
            response.request.method == "POST"
            and parsed.path == self.settings.verify_path
            and is_allowed_host_url(
                response.url, self.settings.allowed_hosts
            )
        )

    def _wait_for_source_change(
        self, frame: Frame, previous: tuple[str, str]
    ) -> None:
        def changed_within(timeout_ms: int) -> bool:
            deadline = time.monotonic() + timeout_ms / 1000.0
            while time.monotonic() < deadline:
                try:
                    target = frame.locator(".tc-instruction-icon img").first
                    background = frame.locator("#slideBg").first
                    current = (
                        target.get_attribute("src") or "",
                        self._background_url(background),
                    )
                    if current != previous and all(current):
                        return True
                except (PlaywrightError, CaptchaAutomationError):
                    pass
                self.page.wait_for_timeout(200)
            return False

        if changed_within(self.settings.image_change_timeout_ms):
            return

        refresh = frame.locator("#reload").first
        if refresh.count() == 0 or not refresh.is_visible():
            raise CaptchaAutomationError("验证码失败后图片没有刷新")
        refresh.click()
        self._random_pause()
        if not changed_within(self.settings.image_change_timeout_ms):
            raise CaptchaAutomationError("刷新后验证码图片仍未更新")

    def _random_pause(self) -> None:
        delay = self._delay_sampler(
            self.settings.click_delay_min_ms,
            self.settings.click_delay_max_ms,
        )
        self.page.wait_for_timeout(delay)

    def _progress(self, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(message)
