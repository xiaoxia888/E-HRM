#!/usr/bin/env python3
"""Find ordered line-art symbols with multi-scale/rotation Chamfer matching."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class SymbolTemplate:
    index: int
    source_bbox: tuple[int, int, int, int]
    foreground: np.ndarray
    edges: np.ndarray


@dataclass(frozen=True)
class Match:
    index: int
    score: float
    center: tuple[int, int]
    matched_bbox: tuple[int, int, int, int]
    source_bbox: tuple[int, int, int, int]
    scale: float
    angle: float
    aspect_ratio: float
    template_size: tuple[int, int]


@dataclass(frozen=True)
class MatcherConfig:
    scales: tuple[float, ...]
    angles: tuple[float, ...]
    aspect_ratios: tuple[float, ...]
    canny_low: int = 40
    canny_high: int = 120
    dark_threshold: int = 70
    blackhat_size: int = 21
    max_chamfer_distance: float = 10.0
    chamfer_weight: float = 0.82
    darkness_weight: float = 0.18
    symbol_gap: int = 5
    min_symbol_area: int = 25


def _odd(value: int) -> int:
    value = max(3, int(value))
    return value if value % 2 else value + 1


def _remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    clean = np.zeros_like(mask)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area:
            clean[labels == label] = 255
    return clean


def _runs(values: Iterable[int], max_gap: int) -> list[tuple[int, int]]:
    columns = list(values)
    if not columns:
        return []
    result: list[tuple[int, int]] = []
    start = previous = columns[0]
    for column in columns[1:]:
        if column - previous > max_gap + 1:
            result.append((start, previous + 1))
            start = column
        previous = column
    result.append((start, previous + 1))
    return result


def extract_symbol_templates(
    target_bgr: np.ndarray,
    *,
    symbol_gap: int = 5,
    min_symbol_area: int = 25,
) -> tuple[list[SymbolTemplate], np.ndarray]:
    """Split symbols left-to-right using the foreground's vertical projection."""
    gray = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, foreground = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )
    foreground = _remove_small_components(foreground, max(2, min_symbol_area // 8))

    active_columns = np.flatnonzero(np.any(foreground > 0, axis=0)).tolist()
    column_runs = _runs(active_columns, symbol_gap)
    templates: list[SymbolTemplate] = []

    for x1, x2 in column_runs:
        section = foreground[:, x1:x2]
        ys, xs = np.nonzero(section)
        if len(xs) < min_symbol_area:
            continue
        y1, y2 = int(ys.min()), int(ys.max()) + 1
        real_x1, real_x2 = x1 + int(xs.min()), x1 + int(xs.max()) + 1
        crop = foreground[y1:y2, real_x1:real_x2]
        edges = cv2.morphologyEx(
            crop, cv2.MORPH_GRADIENT, np.ones((3, 3), dtype=np.uint8)
        )
        templates.append(
            SymbolTemplate(
                index=len(templates) + 1,
                source_bbox=(real_x1, y1, real_x2, y2),
                foreground=crop,
                edges=edges,
            )
        )

    if not templates:
        raise ValueError("No symbols were extracted from the target image")
    return templates, foreground


def build_background_features(
    background_bgr: np.ndarray, config: MatcherConfig
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return edge map, truncated distance transform, and dark-stroke likelihood."""
    gray = cv2.cvtColor(background_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    size = _odd(config.blackhat_size)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    closed = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, kernel)
    blackhat = cv2.subtract(closed, blurred).astype(np.float32) / 255.0
    absolute_dark = np.clip(
        (float(config.dark_threshold) - blurred.astype(np.float32))
        / max(float(config.dark_threshold), 1.0),
        0.0,
        1.0,
    )
    dark_likelihood = np.maximum(absolute_dark, np.clip(blackhat * 2.2, 0.0, 1.0))

    raw_edges = cv2.Canny(blurred, config.canny_low, config.canny_high)
    dark_gate = np.where(dark_likelihood >= 0.10, 255, 0).astype(np.uint8)
    dark_gate = cv2.dilate(dark_gate, np.ones((5, 5), np.uint8))
    candidate_edges = cv2.bitwise_and(raw_edges, dark_gate)

    # DistanceTransform measures distance to zero pixels, so edges become zero.
    inverse_edges = np.where(candidate_edges > 0, 0, 255).astype(np.uint8)
    distance = cv2.distanceTransform(inverse_edges, cv2.DIST_L2, 3)
    distance = np.minimum(distance, config.max_chamfer_distance).astype(np.float32)
    return candidate_edges, distance, dark_likelihood.astype(np.float32)


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
    bound_width = max(3, int(math.ceil(scaled_height * sine + scaled_width * cosine)))
    bound_height = max(3, int(math.ceil(scaled_height * cosine + scaled_width * sine)))
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


def find_best_match(
    template: SymbolTemplate,
    distance: np.ndarray,
    dark_likelihood: np.ndarray,
    config: MatcherConfig,
) -> Match:
    """Find the lowest combined Chamfer/dark-stroke score for one symbol."""
    image_height, image_width = distance.shape
    darkness_penalty = (1.0 - dark_likelihood).astype(np.float32)
    best: Optional[Match] = None

    for scale in config.scales:
        for aspect_ratio in config.aspect_ratios:
            # Rotate the original for every angle to avoid repeated resize artefacts.
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
                min_value, _, min_location, _ = cv2.minMaxLoc(score_map)

                if best is None or min_value < best.score:
                    x1, y1 = min_location
                    x2, y2 = x1 + width, y1 + height
                    best = Match(
                        index=template.index,
                        score=float(min_value),
                        center=((x1 + x2) // 2, (y1 + y2) // 2),
                        matched_bbox=(x1, y1, x2, y2),
                        source_bbox=template.source_bbox,
                        scale=float(scale),
                        angle=float(angle),
                        aspect_ratio=float(aspect_ratio),
                        template_size=(width, height),
                    )

    if best is None:
        raise ValueError(f"No valid transform for symbol {template.index}")
    return best


def match_symbols(
    target_bgr: np.ndarray,
    background_bgr: np.ndarray,
    config: MatcherConfig,
) -> tuple[list[SymbolTemplate], list[Match], dict[str, np.ndarray]]:
    templates, target_foreground = extract_symbol_templates(
        target_bgr,
        symbol_gap=config.symbol_gap,
        min_symbol_area=config.min_symbol_area,
    )
    candidate_edges, distance, dark_likelihood = build_background_features(
        background_bgr, config
    )
    matches = [
        find_best_match(template, distance, dark_likelihood, config)
        for template in templates
    ]
    debug = {
        "target_foreground": target_foreground,
        "background_edges": candidate_edges,
        "distance": distance,
        "dark_likelihood": dark_likelihood,
    }
    return templates, matches, debug


def draw_matches(background_bgr: np.ndarray, matches: Sequence[Match]) -> np.ndarray:
    output = background_bgr.copy()
    red = (35, 35, 255)
    for match in matches:
        x1, y1, x2, y2 = match.matched_bbox
        margin = max(8, int(round(max(x2 - x1, y2 - y1) * 0.08)))
        center = match.center
        axes = (
            max(8, (x2 - x1) // 2 + margin),
            max(8, (y2 - y1) // 2 + margin),
        )
        cv2.ellipse(output, center, axes, 0, 0, 360, red, 5, cv2.LINE_AA)

        label_center = (max(17, x1 - 2), max(17, y1 - 2))
        cv2.circle(output, label_center, 17, red, -1, cv2.LINE_AA)
        text = str(match.index)
        (text_width, text_height), _ = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
        )
        cv2.putText(
            output,
            text,
            (
                label_center[0] - text_width // 2,
                label_center[1] + text_height // 2,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return output


def _parse_range(text: str) -> tuple[float, ...]:
    """Parse either comma-separated numbers or start:stop:step (inclusive)."""
    if ":" not in text:
        values = tuple(float(item) for item in text.split(",") if item.strip())
        if not values:
            raise argparse.ArgumentTypeError("Expected at least one number")
        return values

    parts = text.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Range must be start:stop:step")
    start, stop, step = (float(part) for part in parts)
    if step == 0 or (stop - start) * step < 0:
        raise argparse.ArgumentTypeError("Range step has the wrong direction")
    values: list[float] = []
    current = start
    comparison = (lambda value: value <= stop + 1e-9) if step > 0 else (
        lambda value: value >= stop - 1e-9
    )
    while comparison(current):
        values.append(round(current, 10))
        current += step
    return tuple(values)


def _write_debug_images(
    debug_dir: Path,
    templates: Sequence[SymbolTemplate],
    debug: dict[str, np.ndarray],
) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(debug_dir / "target_foreground.png"), debug["target_foreground"])
    cv2.imwrite(str(debug_dir / "background_edges.png"), debug["background_edges"])
    distance_view = np.clip(
        debug["distance"] / max(float(debug["distance"].max()), 1.0) * 255.0,
        0,
        255,
    ).astype(np.uint8)
    dark_view = np.clip(debug["dark_likelihood"] * 255.0, 0, 255).astype(np.uint8)
    cv2.imwrite(str(debug_dir / "distance_transform.png"), distance_view)
    cv2.imwrite(str(debug_dir / "dark_likelihood.png"), dark_view)
    for template in templates:
        cv2.imwrite(
            str(debug_dir / f"template_{template.index:02d}.png"),
            template.foreground,
        )


def _read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return image


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find ordered line-art symbols using Chamfer matching."
    )
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--debug-dir", type=Path)
    parser.add_argument("--scales", type=_parse_range, default=_parse_range("0.8:2.4:0.2"))
    parser.add_argument("--angles", type=_parse_range, default=_parse_range("-30:30:5"))
    parser.add_argument(
        "--aspect-ratios", type=_parse_range, default=_parse_range("0.75,1.0,1.25")
    )
    parser.add_argument("--canny-low", type=int, default=40)
    parser.add_argument("--canny-high", type=int, default=120)
    parser.add_argument("--dark-threshold", type=int, default=70)
    parser.add_argument("--blackhat-size", type=int, default=21)
    parser.add_argument("--max-chamfer-distance", type=float, default=10.0)
    parser.add_argument("--chamfer-weight", type=float, default=0.82)
    parser.add_argument("--darkness-weight", type=float, default=0.18)
    parser.add_argument("--symbol-gap", type=int, default=5)
    parser.add_argument("--min-symbol-area", type=int, default=25)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not math.isclose(args.chamfer_weight + args.darkness_weight, 1.0, abs_tol=1e-6):
        raise ValueError("--chamfer-weight and --darkness-weight must add up to 1")

    config = MatcherConfig(
        scales=tuple(args.scales),
        angles=tuple(args.angles),
        aspect_ratios=tuple(args.aspect_ratios),
        canny_low=args.canny_low,
        canny_high=args.canny_high,
        dark_threshold=args.dark_threshold,
        blackhat_size=args.blackhat_size,
        max_chamfer_distance=args.max_chamfer_distance,
        chamfer_weight=args.chamfer_weight,
        darkness_weight=args.darkness_weight,
        symbol_gap=args.symbol_gap,
        min_symbol_area=args.min_symbol_area,
    )

    target = _read_image(args.target)
    background = _read_image(args.background)
    templates, matches, debug = match_symbols(target, background, config)
    annotated = draw_matches(background, matches)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), annotated):
        raise OSError(f"Could not write output image: {args.output}")

    json_output = args.json_output or args.output.with_suffix(".json")
    json_output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target": str(args.target),
        "background": str(args.background),
        "output": str(args.output),
        "config": asdict(config),
        "matches": [asdict(match) for match in matches],
    }
    json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.debug_dir:
        _write_debug_images(args.debug_dir, templates, debug)

    for match in matches:
        print(
            f"symbol={match.index} score={match.score:.4f} "
            f"center={match.center} scale={match.scale:.2f} "
            f"angle={match.angle:.1f} aspect={match.aspect_ratio:.2f}"
        )
    print(f"annotated image: {args.output}")
    print(f"match data: {json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
