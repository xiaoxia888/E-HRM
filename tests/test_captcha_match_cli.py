import json
from pathlib import Path

import cv2
import numpy as np

from ehrm.entrypoints.captcha_match_cli import main


def test_offline_captcha_match_cli_writes_analysis_images(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "attempt_01"
    input_dir.mkdir()
    target = np.full((70, 210, 3), 200, np.uint8)
    cv2.rectangle(target, (15, 15), (50, 52), (0, 0, 0), 5)
    cv2.circle(target, (100, 34), 20, (0, 0, 0), 5)
    triangle = np.array([[160, 54], [180, 14], [200, 54]], np.int32)
    cv2.polylines(target, [triangle], True, (0, 0, 0), 5)
    background = np.full((240, 320, 3), 225, np.uint8)
    background[35:75, 40:78] = target[14:54, 14:52]
    background[140:181, 200:241] = target[14:55, 79:120]
    background[45:87, 245:286] = target[13:55, 159:200]
    assert cv2.imwrite(str(input_dir / "1_target.png"), target)
    assert cv2.imwrite(str(input_dir / "2_background.png"), background)

    output_dir = tmp_path / "generated-result"
    exit_code = main(
        [
            "--target",
            str(input_dir / "1_target.png"),
            "--background",
            str(input_dir / "2_background.png"),
            "--output-dir",
            str(output_dir),
            "--fast",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "1_target.png").is_file()
    assert (output_dir / "2_background.png").is_file()
    assert (output_dir / "3_result.png").is_file()
    assert (output_dir / "4_target_foreground.png").is_file()
    assert (output_dir / "11_background_candidate_edges.png").is_file()
    assert (output_dir / "13_selected_matches.png").is_file()
    report = json.loads(
        (output_dir / "analysis.json").read_text(encoding="utf-8")
    )
    assert report["matching_error"] is None
    assert len(report["selected_matches"]) == 3
