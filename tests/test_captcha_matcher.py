from dataclasses import replace

import cv2
import numpy as np

from ehrm.browser.captcha_matcher import ChamferConfig, match_captcha_symbols


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
