from dataclasses import replace

import cv2
import numpy as np

from ehrm.browser.captcha_matcher import (
    CaptchaMatch,
    ChamferConfig,
    _select_joint_matches,
    match_captcha_symbols,
)


def test_chamfer_matcher_keeps_target_order() -> None:
    target = np.full((70, 210, 3), 200, np.uint8)
    cv2.rectangle(target, (15, 15), (50, 52), (0, 0, 0), 5)
    cv2.circle(target, (100, 34), 20, (0, 0, 0), 5)
    triangle = np.array([[160, 54], [180, 14], [200, 54]], np.int32)
    cv2.polylines(target, [triangle], True, (0, 0, 0), 5)

    background = np.full((240, 320, 3), 225, np.uint8)
    background[35:75, 40:78] = target[14:54, 14:52]
    background[140:181, 200:241] = target[14:55, 79:120]
    background[45:87, 245:286] = target[13:55, 159:200]

    config = replace(
        ChamferConfig(),
        scales=(1.0,),
        angles=(0.0,),
        aspect_ratios=(1.0,),
        dark_threshold=100,
    )
    progress: list[tuple[int, int]] = []
    matches = match_captcha_symbols(
        target,
        background,
        config,
        progress_callback=lambda completed, total: progress.append(
            (completed, total)
        ),
    )

    assert [match.index for match in matches] == [1, 2, 3]
    assert progress == [(1, 3), (2, 3), (3, 3)]
    expected = [(59, 55), (220, 160), (265, 65)]
    for match, center in zip(matches, expected, strict=True):
        assert abs(match.center[0] - center[0]) <= 4
        assert abs(match.center[1] - center[1]) <= 4


def test_joint_matcher_rejects_overlap_and_inconsistent_scale() -> None:
    def candidate(
        index: int,
        score: float,
        center: tuple[int, int],
        bbox: tuple[int, int, int, int],
        scale: float,
    ) -> CaptchaMatch:
        return CaptchaMatch(
            index=index,
            score=score,
            center=center,
            matched_bbox=bbox,
            scale=scale,
            angle=0.0,
            aspect_ratio=1.0,
        )

    symbol_1 = candidate(1, 0.0845, (436, 283), (399, 247, 473, 320), 1.6)
    symbol_2_overlap = candidate(
        2,
        0.1609,
        (430, 306),
        (411, 285, 449, 328),
        0.8,
    )
    symbol_2_wrong_scale = candidate(
        2,
        0.1661,
        (516, 367),
        (495, 345, 537, 389),
        1.0,
    )
    symbol_2_correct = candidate(
        2,
        0.2032,
        (126, 42),
        (92, 0, 160, 84),
        1.6,
    )
    symbol_3 = candidate(3, 0.1054, (120, 120), (100, 92, 140, 148), 1.6)

    selected = _select_joint_matches(
        [
            [symbol_1],
            [symbol_2_overlap, symbol_2_wrong_scale, symbol_2_correct],
            [symbol_3],
        ],
        ChamferConfig(),
    )

    assert [match.center for match in selected] == [
        (436, 283),
        (126, 42),
        (120, 120),
    ]
