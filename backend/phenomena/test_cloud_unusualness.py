import unittest
from datetime import UTC, datetime

import numpy as np

from backend.phenomena.cloud_unusualness import (
    CloudPatch,
    classify_patches,
    describe_patch,
    load_cloud_unusualness,
    score_patches,
)
from backend.phenomena.cloud_volume import CloudVolume


class CloudUnusualnessTests(unittest.TestCase):
    def test_variation_responds_to_vertical_and_horizontal_structure(self) -> None:
        clear = np.zeros((3, 6, 6), dtype=np.float32)
        sheet = clear.copy()
        sheet[1] = 0.5
        textured = sheet.copy()
        textured[1, :, ::2] = 1
        bounds = (30.0, 31.5, -100.0, -98.5)

        patches = [
            describe_patch(field, "Test", bounds) for field in (clear, sheet, textured)
        ]
        scores = score_patches(patches)

        self.assertEqual(scores[0].score, 0)
        self.assertEqual(patches[1].horizontal_variation, 0)
        self.assertGreater(patches[1].vertical_variation, 0)
        self.assertGreater(patches[2].horizontal_variation, 0)
        self.assertGreater(patches[2].variation, patches[1].variation)
        self.assertGreater(scores[2].score, scores[1].score)

    def test_cover_extremes_reduce_interestingness(self) -> None:
        patches = [
            CloudPatch("Test", 30, 31.5, -100, -98.5, 0.1, 0.1, cover)
            for cover in (0.05, 0.5, 0.95)
        ]
        scores = score_patches(patches)

        self.assertEqual([score.variation_percentile for score in scores], [50] * 3)
        self.assertAlmostEqual(scores[0].cover_factor, scores[2].cover_factor)
        self.assertGreater(scores[1].score, scores[0].score)
        self.assertGreater(scores[1].score, scores[2].score)

    def test_icon_volume_ranks_its_cloudy_tile(self) -> None:
        latitudes = np.arange(85, 16.75, -0.25)
        longitudes = np.arange(170, 310.25, 0.25)
        cloud_fraction = np.zeros(
            (3, len(latitudes), len(longitudes)), dtype=np.float32
        )
        rows = (latitudes >= 24.75) & (latitudes < 26.25)
        columns = (longitudes >= 234.75) & (longitudes < 236.25)
        cloud_fraction[1][np.ix_(rows, columns)] = 0.8
        aleutian_rows = (latitudes >= 50.25) & (latitudes < 51.75)
        aleutian_columns = (longitudes >= 171) & (longitudes < 172.5)
        cloud_fraction[1][np.ix_(aleutian_rows, aleutian_columns)] = 0.6
        volume = CloudVolume(
            cloud_fraction=cloud_fraction,
            latitudes=latitudes,
            longitudes=longitudes,
            altitudes_km=np.array([0.5, 1.0, 1.5]),
            valid_time=datetime(2026, 9, 24, 12, tzinfo=UTC),
            source_url="https://example.com/icon/clc/",
        )

        result = load_cloud_unusualness(volume)
        features = classify_patches(volume)["features"]
        highest = max(features, key=lambda feature: feature["properties"]["score"])

        self.assertEqual(
            {feature["properties"]["region"] for feature in features},
            {"North America", "Alaska", "Western Aleutians", "Hawaii"},
        )
        self.assertGreater(len(features), 680)
        self.assertEqual(
            len({feature["properties"]["id"] for feature in features}),
            len(features),
        )
        self.assertTrue(
            any(feature["properties"]["id"] == "50.25:-180.00" for feature in features)
        )
        self.assertTrue(
            any(feature["properties"]["id"] == "17.25:-180.00" for feature in features)
        )
        western_aleutian = next(
            feature
            for feature in features
            if feature["properties"]["id"] == "50.25:171.00"
        )
        self.assertGreater(western_aleutian["properties"]["vertical_variation"], 0)
        self.assertEqual(
            western_aleutian["geometry"]["coordinates"][0][0], [171, 50.25]
        )
        self.assertEqual(highest["properties"]["id"], "24.75:-125.25")
        self.assertGreater(highest["properties"]["vertical_variation"], 0)
        self.assertEqual(result.forecast_time, "2026-09-24T12:00+00:00")


if __name__ == "__main__":
    unittest.main()
