import math
import unittest

from phenomena.storm.shape_complexity import score_shape


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


if __name__ == "__main__":
    unittest.main()
