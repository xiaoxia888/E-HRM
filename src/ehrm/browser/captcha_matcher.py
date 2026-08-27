from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import product

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
    bbox: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class _BackgroundFeatureMaps:
    gray: np.ndarray
    blurred: np.ndarray
    blackhat: np.ndarray
    dark_likelihood: np.ndarray
    raw_edges: np.ndarray
    dark_gate: np.ndarray
    candidate_edges: np.ndarray
    distance: np.ndarray


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
    coarse_step: int = 2
    refinement_radius: int = 1
    joint_candidate_count: int = 5
    candidate_center_distance: int = 25
    maximum_pair_overlap_ratio: float = 0.15
    scale_consistency_weight: float = 0.10
    parallel_workers: int = 3


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


def _target_foreground(
    target_bgr: np.ndarray,
    config: ChamferConfig,
) -> np.ndarray:
    gray = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, foreground = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )
    return _remove_small_components(
        foreground, max(2, config.min_symbol_area // 8)
    )


def _extract_templates(
    target_bgr: np.ndarray, config: ChamferConfig
) -> list[_Template]:
    foreground = _target_foreground(target_bgr, config)

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
                bbox=(real_x1, y1, real_x2, y2),
            )
        )

    if not templates:
        raise ValueError("目标图片中没有提取到符号")
    return templates


def _background_feature_maps(
    background_bgr: np.ndarray,
    config: ChamferConfig,
) -> _BackgroundFeatureMaps:
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
    return _BackgroundFeatureMaps(
        gray=gray,
        blurred=blurred,
        blackhat=blackhat,
        dark_likelihood=dark_likelihood,
        raw_edges=raw_edges,
        dark_gate=dark_gate,
        candidate_edges=candidate_edges,
        distance=distance,
    )


def _background_features(
    background_bgr: np.ndarray, config: ChamferConfig
) -> tuple[np.ndarray, np.ndarray]:
    features = _background_feature_maps(background_bgr, config)
    return features.distance, features.dark_likelihood


def captcha_debug_images(
    target_bgr: np.ndarray,
    background_bgr: np.ndarray,
    config: ChamferConfig | None = None,
) -> dict[str, np.ndarray]:
    """Builds images for every important preprocessing stage."""

    resolved = config or ChamferConfig()
    foreground = _target_foreground(target_bgr, resolved)
    templates = _extract_templates(target_bgr, resolved)
    segments = target_bgr.copy()
    colors = ((0, 140, 255), (40, 180, 40), (220, 80, 40))
    for template in templates:
        x1, y1, x2, y2 = template.bbox
        color = colors[(template.index - 1) % len(colors)]
        cv2.rectangle(segments, (x1, y1), (x2 - 1, y2 - 1), color, 1)
        cv2.putText(
            segments,
            str(template.index),
            (x1, max(10, y1 + 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            color,
            1,
            cv2.LINE_AA,
        )

    features = _background_feature_maps(background_bgr, resolved)
    blackhat = np.clip(features.blackhat * 255.0, 0, 255).astype(np.uint8)
    darkness = np.clip(
        features.dark_likelihood * 255.0, 0, 255
    ).astype(np.uint8)
    distance = np.clip(
        features.distance / max(resolved.max_chamfer_distance, 1.0) * 255.0,
        0,
        255,
    ).astype(np.uint8)
    return {
        "4_target_foreground.png": foreground,
        "5_target_segments.png": segments,
        "6_background_gray.png": features.gray,
        "7_background_blackhat.png": blackhat,
        "8_background_raw_edges.png": features.raw_edges,
        "9_background_dark_likelihood.png": darkness,
        "10_background_dark_gate.png": features.dark_gate,
        "11_background_candidate_edges.png": features.candidate_edges,
        "12_background_distance.png": distance,
    }


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


def _evaluate_transform(
    template: _Template,
    distance: np.ndarray,
    darkness_penalty: np.ndarray,
    config: ChamferConfig,
    *,
    scale: float,
    angle: float,
    aspect_ratio: float,
) -> CaptchaMatch | None:
    image_height, image_width = distance.shape
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
        return None
    edge_kernel = (edges > 0).astype(np.float32)
    foreground_kernel = (foreground > 0).astype(np.float32)
    edge_count = float(edge_kernel.sum())
    foreground_count = float(foreground_kernel.sum())
    if edge_count < 8 or foreground_count < 8:
        return None

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
    x1, y1 = location
    x2, y2 = x1 + width, y1 + height
    return CaptchaMatch(
        index=template.index,
        score=float(minimum),
        center=((x1 + x2) // 2, (y1 + y2) // 2),
        matched_bbox=(x1, y1, x2, y2),
        scale=float(scale),
        angle=float(angle),
        aspect_ratio=float(aspect_ratio),
    )


def _coarse_values(values: tuple[float, ...], step: int) -> tuple[float, ...]:
    if step <= 1 or len(values) <= 2:
        return values
    selected = list(values[::step])
    if selected[-1] != values[-1]:
        selected.append(values[-1])
    return tuple(selected)


def _neighbor_values(
    values: tuple[float, ...], selected: float, radius: int
) -> tuple[float, ...]:
    index = min(range(len(values)), key=lambda item: abs(values[item] - selected))
    start = max(0, index - max(0, radius))
    stop = min(len(values), index + max(0, radius) + 1)
    return values[start:stop]


def _distinct_matches(
    candidates: Iterable[CaptchaMatch],
    *,
    limit: int,
    minimum_center_distance: int,
) -> list[CaptchaMatch]:
    distinct: list[CaptchaMatch] = []
    minimum_distance_squared = minimum_center_distance**2
    for candidate in sorted(candidates, key=lambda item: item.score):
        if any(
            (candidate.center[0] - selected.center[0]) ** 2
            + (candidate.center[1] - selected.center[1]) ** 2
            <= minimum_distance_squared
            for selected in distinct
        ):
            continue
        distinct.append(candidate)
        if len(distinct) >= max(1, limit):
            break
    return distinct


def _candidate_matches(
    template: _Template,
    distance: np.ndarray,
    dark_likelihood: np.ndarray,
    config: ChamferConfig,
) -> list[CaptchaMatch]:
    """Returns several spatial alternatives for joint symbol assignment."""

    darkness_penalty = (1.0 - dark_likelihood).astype(np.float32)
    coarse_scales = _coarse_values(config.scales, config.coarse_step)
    coarse_angles = _coarse_values(config.angles, config.coarse_step)
    coarse_matches: list[CaptchaMatch] = []
    for scale in coarse_scales:
        for aspect_ratio in config.aspect_ratios:
            for angle in coarse_angles:
                candidate = _evaluate_transform(
                    template,
                    distance,
                    darkness_penalty,
                    config,
                    scale=scale,
                    angle=angle,
                    aspect_ratio=aspect_ratio,
                )
                if candidate is not None:
                    coarse_matches.append(candidate)
    seeds = _distinct_matches(
        coarse_matches,
        limit=config.joint_candidate_count,
        minimum_center_distance=config.candidate_center_distance,
    )
    if not seeds:
        raise ValueError(f"符号 {template.index} 没有可用匹配")

    refinement_parameters: set[tuple[float, float, float]] = set()
    for candidate in seeds:
        for scale in _neighbor_values(
            config.scales, candidate.scale, config.refinement_radius
        ):
            for aspect_ratio in _neighbor_values(
                config.aspect_ratios,
                candidate.aspect_ratio,
                config.refinement_radius,
            ):
                for angle in _neighbor_values(
                    config.angles,
                    candidate.angle,
                    config.refinement_radius,
                ):
                    refinement_parameters.add((scale, angle, aspect_ratio))

    refined_matches: list[CaptchaMatch] = []
    for scale, angle, aspect_ratio in sorted(refinement_parameters):
        candidate = _evaluate_transform(
            template,
            distance,
            darkness_penalty,
            config,
            scale=scale,
            angle=angle,
            aspect_ratio=aspect_ratio,
        )
        if candidate is not None:
            refined_matches.append(candidate)
    return _distinct_matches(
        [*coarse_matches, *refined_matches],
        limit=config.joint_candidate_count,
        minimum_center_distance=config.candidate_center_distance,
    )


def _pair_overlap_ratio(first: CaptchaMatch, second: CaptchaMatch) -> float:
    first_x1, first_y1, first_x2, first_y2 = first.matched_bbox
    second_x1, second_y1, second_x2, second_y2 = second.matched_bbox
    overlap_width = max(0, min(first_x2, second_x2) - max(first_x1, second_x1))
    overlap_height = max(
        0,
        min(first_y2, second_y2) - max(first_y1, second_y1),
    )
    intersection = overlap_width * overlap_height
    first_area = max(1, (first_x2 - first_x1) * (first_y2 - first_y1))
    second_area = max(
        1,
        (second_x2 - second_x1) * (second_y2 - second_y1),
    )
    return intersection / min(first_area, second_area)


def _select_joint_matches(
    rankings: list[list[CaptchaMatch]],
    config: ChamferConfig,
) -> list[CaptchaMatch]:
    best: tuple[float, tuple[CaptchaMatch, ...]] | None = None
    for combination in product(*rankings):
        if any(
            _pair_overlap_ratio(first, second)
            > config.maximum_pair_overlap_ratio
            for offset, first in enumerate(combination)
            for second in combination[offset + 1 :]
        ):
            continue
        scales = [candidate.scale for candidate in combination]
        scale_penalty = (
            max(scales) - min(scales)
        ) * config.scale_consistency_weight
        total_score = sum(candidate.score for candidate in combination)
        objective = total_score + scale_penalty
        if best is None or objective < best[0]:
            best = (objective, combination)
    if best is None:
        raise ValueError("验证码候选位置相互重叠，无法完成联合匹配")
    return sorted(best[1], key=lambda item: item.index)


def rank_captcha_candidates(
    target_bgr: np.ndarray,
    background_bgr: np.ndarray,
    config: ChamferConfig | None = None,
    *,
    limit_per_symbol: int = 5,
    minimum_center_distance: int = 25,
) -> dict[int, tuple[CaptchaMatch, ...]]:
    """Exhaustively ranks spatially distinct candidates for offline diagnosis."""

    resolved = config or ChamferConfig()
    templates = _extract_templates(target_bgr, resolved)
    distance, dark_likelihood = _background_features(
        background_bgr,
        resolved,
    )
    darkness_penalty = (1.0 - dark_likelihood).astype(np.float32)
    rankings: dict[int, tuple[CaptchaMatch, ...]] = {}
    for template in templates:
        candidates: list[CaptchaMatch] = []
        for scale in resolved.scales:
            for aspect_ratio in resolved.aspect_ratios:
                for angle in resolved.angles:
                    candidate = _evaluate_transform(
                        template,
                        distance,
                        darkness_penalty,
                        resolved,
                        scale=scale,
                        angle=angle,
                        aspect_ratio=aspect_ratio,
                    )
                    if candidate is not None:
                        candidates.append(candidate)
        candidates.sort(key=lambda item: item.score)
        rankings[template.index] = tuple(
            _distinct_matches(
                candidates,
                limit=limit_per_symbol,
                minimum_center_distance=minimum_center_distance,
            )
        )
    return rankings


def render_captcha_matches(
    background_bgr: np.ndarray,
    matches: Iterable[CaptchaMatch],
) -> np.ndarray:
    """Renders selected bounding boxes, centers and transform parameters."""

    result = background_bgr.copy()
    colors = ((0, 140, 255), (40, 180, 40), (220, 80, 40))
    for match in matches:
        color = colors[(match.index - 1) % len(colors)]
        x1, y1, x2, y2 = match.matched_bbox
        cv2.rectangle(result, (x1, y1), (x2, y2), color, 3)
        cv2.circle(result, match.center, 5, color, -1)
        label = (
            f"S{match.index} {match.score:.4f} "
            f"x{match.scale:.1f} a{match.angle:.0f}"
        )
        cv2.putText(
            result,
            label,
            (max(0, x1), max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            result,
            label,
            (max(0, x1), max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            1,
            cv2.LINE_AA,
        )
    return result


def render_click_sequence(
    background_bgr: np.ndarray,
    matches: Iterable[CaptchaMatch],
) -> np.ndarray:
    """Renders numbered click centers in target-symbol order."""

    result = background_bgr.copy()
    image_height, image_width = result.shape[:2]
    radius = max(12, round(min(image_width, image_height) * 0.04))
    font_scale = max(0.55, radius / 18.0)
    thickness = max(2, round(radius / 7))
    for sequence, match in enumerate(
        sorted(matches, key=lambda item: item.index),
        start=1,
    ):
        center = match.center
        overlay = result.copy()
        cv2.circle(overlay, center, radius, (0, 140, 255), -1)
        cv2.addWeighted(overlay, 0.35, result, 0.65, 0, result)
        cv2.circle(result, center, radius, (255, 255, 255), thickness)
        cv2.circle(result, center, radius + thickness, (0, 140, 255), 2)
        label = str(sequence)
        (text_width, text_height), _ = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            thickness,
        )
        origin = (
            center[0] - text_width // 2,
            center[1] + text_height // 2,
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
    return result


def render_candidate_rankings(
    background_bgr: np.ndarray,
    rankings: dict[int, tuple[CaptchaMatch, ...]],
) -> np.ndarray:
    """Renders the top distinct alternatives for every target symbol."""

    result = background_bgr.copy()
    colors = ((0, 140, 255), (40, 180, 40), (220, 80, 40))
    for symbol_index, candidates in rankings.items():
        color = colors[(symbol_index - 1) % len(colors)]
        for rank, candidate in enumerate(candidates, start=1):
            x1, y1, x2, y2 = candidate.matched_bbox
            thickness = 3 if rank == 1 else 1
            cv2.rectangle(result, (x1, y1), (x2, y2), color, thickness)
            label = f"S{symbol_index}#{rank} {candidate.score:.3f}"
            label_y = min(result.shape[0] - 5, max(15, y1 + 15 * rank))
            cv2.putText(
                result,
                label,
                (max(0, x1), label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (255, 255, 255),
                3,
                cv2.LINE_AA,
            )
            cv2.putText(
                result,
                label,
                (max(0, x1), label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                color,
                1,
                cv2.LINE_AA,
            )
    return result


def match_captcha_symbols(
    target_bgr: np.ndarray,
    background_bgr: np.ndarray,
    config: ChamferConfig | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[CaptchaMatch]:
    resolved = config or ChamferConfig()
    templates = _extract_templates(target_bgr, resolved)
    distance, dark_likelihood = _background_features(background_bgr, resolved)
    worker_count = max(1, min(resolved.parallel_workers, len(templates)))
    if worker_count == 1:
        rankings = []
        for template in templates:
            rankings.append(
                _candidate_matches(
                    template,
                    distance,
                    dark_likelihood,
                    resolved,
                )
            )
            if progress_callback is not None:
                progress_callback(len(rankings), len(templates))
    else:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="captcha-match",
        ) as executor:
            futures = [
                executor.submit(
                    _candidate_matches,
                    template,
                    distance,
                    dark_likelihood,
                    resolved,
                )
                for template in templates
            ]
            rankings = []
            for future in futures:
                rankings.append(future.result())
                if progress_callback is not None:
                    progress_callback(len(rankings), len(templates))
    matches = _select_joint_matches(rankings, resolved)
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
