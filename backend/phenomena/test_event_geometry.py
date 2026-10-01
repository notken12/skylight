import unittest

from pyproj import Geod

from backend.phenomena.event_geometry import enclosing_circle

GEOD = Geod(ellps="WGS84")


class EventGeometryTests(unittest.TestCase):
    def test_event_circle_contains_an_irregular_storm(self) -> None:
        ring = [
            [-101.0, 39.0],
            [-99.7, 39.0],
            [-99.7, 39.4],
            [-100.6, 39.4],
            [-100.6, 40.0],
            [-101.0, 40.0],
            [-101.0, 39.0],
        ]
        circle = enclosing_circle({"type": "Polygon", "coordinates": [ring]})

        for longitude, latitude in ring:
            _, _, distance_m = GEOD.inv(
                circle.center_longitude,
                circle.center_latitude,
                longitude,
                latitude,
            )
            self.assertLess(distance_m / 1000, circle.radius_km)


if __name__ == "__main__":
    unittest.main()
