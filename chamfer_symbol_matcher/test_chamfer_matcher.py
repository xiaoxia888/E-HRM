import unittest

import cv2
import numpy as np

from chamfer_matcher import MatcherConfig, extract_symbol_templates, match_symbols


class ChamferMatcherTest(unittest.TestCase):
    def _images(self):
        target = np.full((70, 210, 3), 200, np.uint8)
        cv2.rectangle(target, (15, 15), (50, 52), (0, 0, 0), 5)
        cv2.circle(target, (100, 34), 20, (0, 0, 0), 5)
        triangle = np.array([[160, 54], [180, 14], [200, 54]], np.int32)
        cv2.polylines(target, [triangle], True, (0, 0, 0), 5)

        background = np.full((240, 320, 3), 225, np.uint8)
        background[35:75, 40:78] = target[14:54, 14:52]
        background[140:181, 200:241] = target[14:55, 79:120]
        background[45:87, 245:286] = target[13:55, 159:200]
        return target, background

    def test_extracts_symbols_left_to_right(self):
        target, _ = self._images()
        templates, _ = extract_symbol_templates(target)
        self.assertEqual([template.index for template in templates], [1, 2, 3])
        self.assertTrue(
            templates[0].source_bbox[0] < templates[1].source_bbox[0]
            < templates[2].source_bbox[0]
        )

    def test_matches_exact_scale_symbols(self):
        target, background = self._images()
        config = MatcherConfig(
            scales=(1.0,),
            angles=(0.0,),
            aspect_ratios=(1.0,),
            dark_threshold=100,
        )
        _, matches, _ = match_symbols(target, background, config)
        expected = [(59, 55), (220, 160), (265, 65)]
        for match, center in zip(matches, expected):
            self.assertLessEqual(abs(match.center[0] - center[0]), 4)
            self.assertLessEqual(abs(match.center[1] - center[1]), 4)


if __name__ == "__main__":
    unittest.main()

