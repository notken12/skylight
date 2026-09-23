import math
import unittest

import numpy as np
from skimage.draw import disk, ellipse

from shape_complexity import score_mask, score_shape


def oval_ring(
    longitude: float, latitude: float, width: float, height: float
) -> list[list[float]]:
    vertices = [
        [
            longitude + width * math.cos(2 * math.pi * index / 64),
            latitude + height * math.sin(2 * math.pi * index / 64),
        ]
        for index in range(64)
    ]
    return vertices + [vertices[0]]


class ShapeComplexityTests(unittest.TestCase):
    def test_smooth_oval_scores_below_jagged_star(self) -> None:
        oval = {"type": "Polygon", "coordinates": [oval_ring(0, 0, 2, 1)]}
        vertices = [
            [
                (2 if index % 2 == 0 else 0.8) * math.cos(2 * math.pi * index / 16),
                (2 if index % 2 == 0 else 0.8) * math.sin(2 * math.pi * index / 16),
            ]
            for index in range(16)
        ]
        star = {"type": "Polygon", "coordinates": [vertices + [vertices[0]]]}

        self.assertLess(score_shape(oval).score, 1)
        self.assertGreater(score_shape(star).score, 20)

    def test_separate_polygons_add_fragmentation(self) -> None:
        first = [oval_ring(-2, 0, 1, 1)]
        second = [oval_ring(2, 0, 1, 1)]
        single = score_shape({"type": "Polygon", "coordinates": first})
        separated = score_shape(
            {"type": "MultiPolygon", "coordinates": [first, second]}
        )

        self.assertEqual(separated.component_count, 2)
        self.assertAlmostEqual(separated.fragmentation, 0.5, places=2)
        self.assertGreater(separated.score, single.score)

    def test_raster_oval_scores_below_concave_and_separated_masks(self) -> None:
        oval = np.zeros((128, 128), dtype=bool)
        rows, columns = ellipse(64, 64, 16, 38)
        oval[rows, columns] = True

        concave = np.zeros_like(oval)
        concave[20:110, 20:35] = True
        concave[20:110, 90:105] = True
        concave[95:110, 20:105] = True

        separated = np.zeros_like(oval)
        rows, columns = disk((35, 35), 18)
        separated[rows, columns] = True
        rows, columns = disk((90, 90), 18)
        separated[rows, columns] = True

        self.assertLess(score_mask(oval).score, 2)
        self.assertGreater(score_mask(concave).score, 15)
        self.assertGreater(score_mask(separated).score, score_mask(oval).score)
        self.assertEqual(score_mask(separated).component_count, 2)

    def test_single_pixel_noise_does_not_change_raster_score(self) -> None:
        mask = np.zeros((80, 80), dtype=bool)
        rows, columns = disk((40, 40), 18)
        mask[rows, columns] = True
        original = score_mask(mask)
        mask[0, 0] = True

        self.assertEqual(score_mask(mask), original)


if __name__ == "__main__":
    unittest.main()
