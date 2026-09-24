import unittest
from datetime import UTC, datetime, timedelta

import numpy as np

from aurora import classify_auroras
from cameras import Camera
from sunset_weather import CloudCoverGrid


class AuroraTests(unittest.TestCase):
    def test_aurora_regions_match_only_dark_clear_cameras(self) -> None:
        forecast_time = datetime(2026, 9, 23, 12, tzinfo=UTC)
        latitudes = np.arange(65.0, 54.9, -0.25)
        longitudes = np.arange(205.0, 215.1, 0.25)
        cover = np.full((len(latitudes), len(longitudes)), 20, dtype=np.float32)
        cover[:, np.isclose(longitudes, 209.5)] = 75
        cover[:, np.isclose(longitudes, 211.0)] = 75
        cloud = CloudCoverGrid(
            cover, latitudes, longitudes, forecast_time, "https://example.com/gfs"
        )
        data = {
            "Data Format": "[Longitude, Latitude, Aurora]",
            "Observation Time": (forecast_time - timedelta(minutes=45)).isoformat(),
            "Forecast Time": forecast_time.isoformat(),
            "coordinates": [
                [210, 60, 60],
                [211, 60, 90],
                [250, 60, 90],
            ],
        }
        cameras = [
            Camera(
                "Test",
                "clear",
                60,
                -150,
                "https://example.com/clear",
                azimuth_degrees=0,
                bearing_tolerance_degrees=20,
            ),
            Camera(
                "Test",
                "cloudy",
                60,
                -150.5,
                "https://example.com/cloudy",
                azimuth_degrees=0,
                bearing_tolerance_degrees=20,
            ),
            Camera(
                "Test",
                "far",
                60,
                -153,
                "https://example.com/far",
                azimuth_degrees=270,
                bearing_tolerance_degrees=20,
            ),
        ]

        result = classify_auroras(data, cloud, cameras, forecast_time)

        self.assertEqual(len(result.features["features"]), 1)
        feature = result.features["features"][0]
        self.assertEqual(feature["properties"]["aurora_percent"], 60)
        self.assertEqual(feature["properties"]["cloud_cover_percent"], 20)
        self.assertGreater(feature["properties"]["circle"]["radius_km"], 0)
        self.assertEqual(result.cameras[0].event_ids, (feature["properties"]["id"],))
        self.assertEqual(result.cameras[1].event_ids, ())
        self.assertEqual(result.cameras[1].cloud_cover_percent, 75)
        self.assertEqual(result.cameras[2].event_ids, ())

    def test_daylight_cells_do_not_form_regions(self) -> None:
        forecast_time = datetime(2026, 9, 23, 22, tzinfo=UTC)
        cloud = CloudCoverGrid(
            np.full((5, 5), 10, dtype=np.float32),
            np.arange(60.5, 59.4, -0.25),
            np.arange(209.5, 210.6, 0.25),
            forecast_time,
            "https://example.com/gfs",
        )
        data = {
            "Data Format": "[Longitude, Latitude, Aurora]",
            "Observation Time": forecast_time.isoformat(),
            "Forecast Time": forecast_time.isoformat(),
            "coordinates": [[210, 60, 80]],
        }

        result = classify_auroras(data, cloud, [], forecast_time)

        self.assertEqual(result.features["features"], [])

    def test_stale_ovation_is_rejected(self) -> None:
        forecast_time = datetime(2026, 9, 23, 12, tzinfo=UTC)
        cloud = CloudCoverGrid(
            np.full((2, 2), 20, dtype=np.float32),
            np.array([60.0, 59.75]),
            np.array([210.0, 210.25]),
            forecast_time,
            "https://example.com/gfs",
        )
        data = {
            "Data Format": "[Longitude, Latitude, Aurora]",
            "Observation Time": forecast_time.isoformat(),
            "Forecast Time": forecast_time.isoformat(),
            "coordinates": [],
        }
        with self.assertRaisesRegex(ValueError, "stale"):
            classify_auroras(data, cloud, [], forecast_time + timedelta(hours=3))


if __name__ == "__main__":
    unittest.main()
