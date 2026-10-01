import unittest
from datetime import UTC, datetime

import numpy as np

from backend.phenomena.icon_weather import (
    cloud_by_altitude,
    icon_cloud_url,
    icon_forecast_cycle,
    icon_height_url,
)


class IconWeatherTests(unittest.TestCase):
    def test_cycle_uses_a_published_forecast_of_the_requested_time(self) -> None:
        cycle, lead = icon_forecast_cycle(datetime(2026, 9, 24, 2, 34, tzinfo=UTC))

        self.assertEqual(cycle, datetime(2026, 9, 23, 18, tzinfo=UTC))
        self.assertEqual(lead, 9)
        self.assertIn("2026092318_009_80_CLC", icon_cloud_url(cycle, lead, 80))
        self.assertIn("2026092318_80_HHL", icon_height_url(cycle, 80))

    def test_cloud_interpolation_respects_height_and_terrain(self) -> None:
        clouds = np.array([[[100, 100]], [[50, 50]], [[0, 0]]], dtype=np.float32)
        heights = np.array([[[3, 3]], [[2, 2]], [[1, 1]]], dtype=np.float32)
        terrain = np.array([[0, 2]], dtype=np.float32)

        volume = cloud_by_altitude(clouds, heights, terrain, np.array([1.5, 2.5]))

        np.testing.assert_allclose(volume[:, 0, 0], [0.25, 0.75])
        np.testing.assert_allclose(volume[:, 0, 1], [0, 0.75])


if __name__ == "__main__":
    unittest.main()
