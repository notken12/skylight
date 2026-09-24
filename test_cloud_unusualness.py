import unittest

import numpy as np

from cloud_unusualness import CloudPatch, boundary_alignment, score_patches
from shape_complexity import ShapeComplexity


class CloudUnusualnessTests(unittest.TestCase):
    def test_large_opaque_sheet_ranks_above_ordinary_patches(self) -> None:
        ordinary_shape = ShapeComplexity(15, 0.1, 0.1, 0.25, 4)
        ordinary = [
            CloudPatch(
                south=30,
                north=31.5,
                west=-100 + index,
                east=-98.5 + index,
                satellite=19,
                cloud_fraction=0.35 + index / 1000,
                valid_fraction=1,
                shape=ordinary_shape,
                alignment=0.2,
                hole_fraction=0.01,
                height_km=2 + index / 100,
                height_spread_km=0.3,
                optical_depth=4 + index / 100,
            )
            for index in range(30)
        ]
        sheet = CloudPatch(
            south=40,
            north=41.5,
            west=-90,
            east=-88.5,
            satellite=19,
            cloud_fraction=0.98,
            valid_fraction=1,
            shape=ShapeComplexity(0, 0, 0, 0, 1),
            alignment=0.9,
            hole_fraction=0,
            height_km=6,
            height_spread_km=0.1,
            optical_depth=25,
        )

        scores = score_patches([*ordinary, sheet])

        self.assertEqual(int(np.argmax(scores)), len(ordinary))
        self.assertTrue(np.all(np.isfinite(scores)))

    def test_parallel_cloud_bands_have_high_alignment(self) -> None:
        bands = np.zeros((64, 64), dtype=bool)
        bands[::8, :] = True

        self.assertGreater(boundary_alignment(bands), 0.9)
        self.assertEqual(boundary_alignment(np.ones((64, 64), dtype=bool)), 0)


if __name__ == "__main__":
    unittest.main()
