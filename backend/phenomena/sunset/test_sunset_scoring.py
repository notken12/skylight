import unittest
from datetime import UTC, datetime

import numpy as np

from backend.phenomena.sunset.sunset_scoring import sunset_band


class SunsetScoringTests(unittest.TestCase):
    def test_sunset_band_wraps_across_utc_midnight(self) -> None:
        latitude = np.array([[40.0]])
        longitude = np.array([[-100.0]])
        self.assertTrue(
            sunset_band(datetime(2026, 9, 24, 0, 30, tzinfo=UTC), latitude, longitude)[
                0, 0
            ]
        )
        self.assertFalse(
            sunset_band(datetime(2026, 9, 23, 12, 0, tzinfo=UTC), latitude, longitude)[
                0, 0
            ]
        )


if __name__ == "__main__":
    unittest.main()
