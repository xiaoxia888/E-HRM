from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ehrm.browser.captcha_matcher import (
    captcha_debug_images,
    match_captcha_symbols,
    rank_captcha_candidates,
    render_candidate_rankings,
    render_captcha_matches,
    render_click_sequence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="离线分析已保存的验证码目标图和背景图，不启动浏览器。",
    )
    parser.add_argument("input_dir", nargs="?", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--target", type=Path, help="目标符号图片文件地址")
    parser.add_argument("--background", type=Path, help="背景图片文件地址")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="结果文件夹；默认在目标图片旁创建带时间戳的结果文件夹",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="跳过耗时较长的全量候选排名，只运行线上同款匹配",
    )
    return parser


def _read_image(path: Path) -> np.ndarray:
    try:
        payload = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise ValueError(f"无法读取图片：{path}") from exc
    image = cv2.imdecode(payload, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"图片格式无效：{path}")
    return image


def _write_png(path: Path, image: np.ndarray) -> None:
    encoded, payload = cv2.imencode(".png", image)
    if not encoded:
        raise ValueError(f"PNG 编码失败：{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload.tofile(path)


def _input_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.target is not None or args.background is not None:
        if args.target is None or args.background is None:
            raise ValueError("--target 和 --background 必须同时提供")
        return (
            args.target.expanduser().resolve(),
            args.background.expanduser().resolve(),
        )
    if args.input_dir is not None:
        input_dir = args.input_dir.expanduser().resolve()
        return input_dir / "1_target.png", input_dir / "2_background.png"
    raise ValueError("请通过 --target 和 --background 指定两张图片")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        target_path, background_path = _input_paths(args)
        output_dir = (
            args.output_dir.expanduser().resolve()
            if args.output_dir is not None
            else target_path.parent
            / f"captcha_result_{datetime.now():%Y%m%d_%H%M%S_%f}"
        )
        target = _read_image(target_path)
        background = _read_image(background_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_png(output_dir / "1_target.png", target)
        _write_png(output_dir / "2_background.png", background)
        for filename, image in captcha_debug_images(target, background).items():
            _write_png(output_dir / filename, image)

        matching_error = ""
        try:
            matches = match_captcha_symbols(target, background)
        except (ValueError, cv2.error) as exc:
            matches = []
            matching_error = str(exc)
        _write_png(
            output_dir / "3_result.png",
            render_click_sequence(background, matches),
        )
        _write_png(
            output_dir / "13_selected_matches.png",
            render_captcha_matches(background, matches),
        )

        rankings = {}
        if not args.fast:
            rankings = rank_captcha_candidates(target, background)
            _write_png(
                output_dir / "14_candidate_rankings.png",
                render_candidate_rankings(background, rankings),
            )

        report = {
            "target": str(target_path),
            "background": str(background_path),
            "matching_error": matching_error or None,
            "selected_matches": [asdict(match) for match in matches],
            "candidate_rankings": {
                str(index): [asdict(candidate) for candidate in candidates]
                for index, candidates in rankings.items()
            },
        }
        report_path = output_dir / "analysis.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, ValueError, cv2.error) as exc:
        print(f"验证码离线分析失败：{exc}")
        return 1

    if matching_error:
        print(f"线上同款匹配未通过：{matching_error}")
    else:
        for match in matches:
            print(
                f"符号 {match.index}: score={match.score:.4f}, "
                f"center={match.center}, scale={match.scale:.1f}, "
                f"angle={match.angle:.0f}, aspect={match.aspect_ratio:.2f}"
            )
    if rankings:
        for index, candidates in rankings.items():
            rendered = ", ".join(
                f"#{rank} score={candidate.score:.4f} center={candidate.center} "
                f"scale={candidate.scale:.1f} angle={candidate.angle:.0f}"
                for rank, candidate in enumerate(candidates, start=1)
            )
            print(f"符号 {index} 候选：{rendered}")
    print(f"分析结果：{output_dir}")
    return 0 if not matching_error else 2


if __name__ == "__main__":
    raise SystemExit(main())
