from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class CaptchaMatch:
    index: int
    score: float
    center: tuple[int, int]
    matched_bbox: tuple[int, int, int, int]
    scale: float
    angle: float
    aspect_ratio: float


@dataclass(frozen=True, slots=True)
class _Template:
    index: int
    foreground: np.ndarray


@dataclass(frozen=True, slots=True)
class ChamferConfig:
    scales: tuple[float, ...] = (
        0.8,
        1.0,
        1.2,
        1.4,
        1.6,
        1.8,
        2.0,
        2.2,
        2.4,
    )
    angles: tuple[float, ...] = (
        -30.0,
        -25.0,
        -20.0,
        -15.0,
        -10.0,
        -5.0,
        0.0,
        5.0,
        10.0,
        15.0,
        20.0,
        25.0,
        30.0,
    )
    aspect_ratios: tuple[float, ...] = (0.75, 1.0, 1.25)
    canny_low: int = 40
    canny_high: int = 120
    dark_threshold: int = 70
    blackhat_size: int = 21
    max_chamfer_distance: float = 10.0
    chamfer_weight: float = 0.82
    darkness_weight: float = 0.18
    symbol_gap: int = 5
    min_symbol_area: int = 25
    maximum_accepted_score: float = 0.22


def _remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    clean = np.zeros_like(mask)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area:
            clean[labels == label] = 255
    return clean


def _column_runs(columns: list[int], max_gap: int) -> list[tuple[int, int]]:
    if not columns:
        return []
    runs: list[tuple[int, int]] = []
    start = previous = columns[0]
    for column in columns[1:]:
        if column - previous > max_gap + 1:
            runs.append((start, previous + 1))
            start = column
        previous = column
    runs.append((start, previous + 1))
    return runs


def _extract_templates(
    target_bgr: np.ndarray, config: ChamferConfig
) -> list[_Template]:
    gray = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, foreground = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )
    foreground = _remove_small_components(
        foreground, max(2, config.min_symbol_area // 8)
    )

    active = np.flatnonzero(np.any(foreground > 0, axis=0)).tolist()
    templates: list[_Template] = []
    for x1, x2 in _column_runs(active, config.symbol_gap):
        section = foreground[:, x1:x2]
        ys, xs = np.nonzero(section)
        if len(xs) < config.min_symbol_area:
            continue
        y1, y2 = int(ys.min()), int(ys.max()) + 1
        real_x1 = x1 + int(xs.min())
        real_x2 = x1 + int(xs.max()) + 1
        templates.append(
            _Template(
                index=len(templates) + 1,
                foreground=foreground[y1:y2, real_x1:real_x2],
            )
        )

    if not templates:
        raise ValueError("目标图片中没有提取到符号")
    return templates


def _background_features(
    background_bgr: np.ndarray, config: ChamferConfig
) -> tuple[np.ndarray, np.ndarray]:
    gray = cv2.cvtColor(background_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    blackhat_size = max(3, config.blackhat_size)
    if blackhat_size % 2 == 0:
        blackhat_size += 1
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (blackhat_size, blackhat_size)
    )
    closed = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, kernel)
    blackhat = cv2.subtract(closed, blurred).astype(np.float32) / 255.0
    absolute_dark = np.clip(
        (float(config.dark_threshold) - blurred.astype(np.float32))
        / max(float(config.dark_threshold), 1.0),
        0.0,
        1.0,
    )
    dark_likelihood = np.maximum(
        absolute_dark, np.clip(blackhat * 2.2, 0.0, 1.0)
    ).astype(np.float32)

    raw_edges = cv2.Canny(blurred, config.canny_low, config.canny_high)
    dark_gate = np.where(dark_likelihood >= 0.10, 255, 0).astype(np.uint8)
    dark_gate = cv2.dilate(dark_gate, np.ones((5, 5), dtype=np.uint8))
    candidate_edges = cv2.bitwise_and(raw_edges, dark_gate)
    inverse_edges = np.where(candidate_edges > 0, 0, 255).astype(np.uint8)
    distance = cv2.distanceTransform(inverse_edges, cv2.DIST_L2, 3)
    distance = np.minimum(distance, config.max_chamfer_distance).astype(np.float32)
    return distance, dark_likelihood


def _transform_mask(
    mask: np.ndarray, scale: float, angle: float, aspect_ratio: float
) -> np.ndarray:
    height, width = mask.shape
    scaled_width = max(3, int(round(width * scale * aspect_ratio)))
    scaled_height = max(3, int(round(height * scale)))
    resized = cv2.resize(
        mask, (scaled_width, scaled_height), interpolation=cv2.INTER_NEAREST
    )
    center = (scaled_width / 2.0, scaled_height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    bound_width = max(
        3, int(math.ceil(scaled_height * sine + scaled_width * cosine))
    )
    bound_height = max(
        3, int(math.ceil(scaled_height * cosine + scaled_width * sine))
    )
    matrix[0, 2] += bound_width / 2.0 - center[0]
    matrix[1, 2] += bound_height / 2.0 - center[1]
    rotated = cv2.warpAffine(
        resized,
        matrix,
        (bound_width, bound_height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    ys, xs = np.nonzero(rotated)
    if len(xs) == 0:
        return rotated
    return rotated[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _best_match(
    template: _Template,
    distance: np.ndarray,
    dark_likelihood: np.ndarray,
    config: ChamferConfig,
) -> CaptchaMatch:
    image_height, image_width = distance.shape
    darkness_penalty = (1.0 - dark_likelihood).astype(np.float32)
    best: CaptchaMatch | None = None

    for scale in config.scales:
        for aspect_ratio in config.aspect_ratios:
            for angle in config.angles:
                foreground = _transform_mask(
                    template.foreground, scale, angle, aspect_ratio
                )
                edges = cv2.morphologyEx(
                    foreground,
                    cv2.MORPH_GRADIENT,
                    np.ones((3, 3), dtype=np.uint8),
                )
                height, width = edges.shape
                if height >= image_height or width >= image_width:
                    continue
                edge_kernel = (edges > 0).astype(np.float32)
                foreground_kernel = (foreground > 0).astype(np.float32)
                edge_count = float(edge_kernel.sum())
                foreground_count = float(foreground_kernel.sum())
                if edge_count < 8 or foreground_count < 8:
                    continue

                chamfer_map = cv2.matchTemplate(
                    distance, edge_kernel, cv2.TM_CCORR
                ) / (edge_count * config.max_chamfer_distance)
                darkness_map = cv2.matchTemplate(
                    darkness_penalty, foreground_kernel, cv2.TM_CCORR
                ) / foreground_count
                score_map = (
                    config.chamfer_weight * chamfer_map
                    + config.darkness_weight * darkness_map
                )
                minimum, _, location, _ = cv2.minMaxLoc(score_map)
                if best is None or minimum < best.score:
                    x1, y1 = location
                    x2, y2 = x1 + width, y1 + height
                    best = CaptchaMatch(
                        index=template.index,
                        score=float(minimum),
                        center=((x1 + x2) // 2, (y1 + y2) // 2),
                        matched_bbox=(x1, y1, x2, y2),
                        scale=float(scale),
                        angle=float(angle),
                        aspect_ratio=float(aspect_ratio),
                    )

    if best is None:
        raise ValueError(f"符号 {template.index} 没有可用匹配")
    return best


def match_captcha_symbols(
    target_bgr: np.ndarray,
    background_bgr: np.ndarray,
    config: ChamferConfig | None = None,
) -> list[CaptchaMatch]:
    resolved = config or ChamferConfig()
    templates = _extract_templates(target_bgr, resolved)
    distance, dark_likelihood = _background_features(background_bgr, resolved)
    matches = [
        _best_match(template, distance, dark_likelihood, resolved)
        for template in templates
    ]
    rejected = [
        match
        for match in matches
        if match.score > resolved.maximum_accepted_score
    ]
    if rejected:
        details = "、".join(
            f"{match.index}:{match.score:.4f}" for match in rejected
        )
        raise ValueError(f"验证码匹配分数超过阈值：{details}")
    return matches
