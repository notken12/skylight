import unittest
from datetime import UTC, datetime, timedelta

from pyproj import Geod

from camera_matching import match_cameras
from cameras import Camera, faa_cameras
from event_geometry import VISUAL_CLOUD_BUFFER_KM, enclosing_circle
from probsevere import classify_storms
from shape_complexity import score_shape

GEOD = Geod(ellps="WGS84")


class EventMatchingTests(unittest.TestCase):
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

    def test_camera_heading_and_range_control_association(self) -> None:
        storms = {
            "features": [
                {
                    "properties": {
                        "id": "storm-a",
                        "circle": {
                            "center_latitude": 40.0,
                            "center_longitude": -100.0,
                            "radius_km": 10.0,
                        },
                        "view_circle": {
                            "center_latitude": 40.0,
                            "center_longitude": -100.0,
                            "radius_km": 50.0,
                        },
                    }
                }
            ]
        }
        cameras = [
            Camera(
                "Test",
                "Facing",
                40.0,
                -100.5,
                "https://example.com/1",
                azimuth_degrees=90,
                bearing_tolerance_degrees=10,
            ),
            Camera(
                "Test",
                "Away",
                40.0,
                -101.5,
                "https://example.com/2",
                azimuth_degrees=270,
                bearing_tolerance_degrees=10,
            ),
            Camera("Test", "Unknown", 40.0, -100.5, "https://example.com/3"),
            Camera(
                "Test",
                "Far",
                40.0,
                -103.0,
                "https://example.com/4",
                azimuth_degrees=90,
                bearing_tolerance_degrees=10,
            ),
        ]

        matches = match_cameras(storms, cameras)

        self.assertEqual(
            [match.event_ids for match in matches], [("storm-a",), (), (), ()]
        )

    def test_nearby_views_match_from_opposite_directions(self) -> None:
        storms = {
            "features": [
                {
                    "properties": {
                        "id": "storm-a",
                        "view_circle": {
                            "center_latitude": 40.0,
                            "center_longitude": -100.0,
                            "radius_km": 50.0,
                        },
                    }
                }
            ]
        }
        cameras = [
            Camera(
                "FAA WeatherCams",
                "East view",
                40.0,
                -100.5,
                "https://example.com/east",
                azimuth_degrees=90,
                bearing_tolerance_degrees=22.5,
            ),
            Camera(
                "FAA WeatherCams",
                "West view",
                40.0,
                -100.5,
                "https://example.com/west",
                azimuth_degrees=270,
                bearing_tolerance_degrees=22.5,
            ),
        ]

        matches = match_cameras(storms, cameras)

        self.assertEqual([match.event_ids for match in matches], [("storm-a",)] * 2)

    def test_storm_instance_preserves_score_inputs(self) -> None:
        ring = [
            [-100.1, 40.0],
            [-99.9, 40.0],
            [-99.9, 40.2],
            [-100.1, 40.2],
            [-100.1, 40.0],
        ]
        data = {
            "product": "ProbSevere 3.0",
            "validTime": "20260923_120000",
            "features": [
                {
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {"ID": "storm-a", "AccumFCD": "4", "COMPREF": "51.2"},
                    "models": {
                        "probsevere": {"PROB": "60"},
                        "probhail": {"PROB": "20"},
                        "probwind": {"PROB": "30"},
                        "probtor": {"PROB": "1"},
                    },
                }
            ],
        }

        instance = classify_storms(data, score_shape, enclosing_circle)["features"][0]
        properties = instance["properties"]

        self.assertEqual(properties["valid_time"], data["validTime"])
        self.assertEqual(
            properties["view_circle"]["radius_km"],
            round(properties["circle"]["radius_km"] + VISUAL_CLOUD_BUFFER_KM, 1),
        )
        self.assertEqual(properties["interestingness"]["severe_probability"], 60)
        self.assertEqual(
            properties["interestingness"]["outline_complexity"],
            properties["outline_shape"]["score"],
        )
        self.assertEqual(
            properties["interestingness"]["score"],
            round((60 + properties["outline_shape"]["score"]) / 2, 1),
        )

    def test_faa_views_keep_individual_bearings(self) -> None:
        current = datetime.now(UTC).isoformat()
        stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        site = {
            "country": "US",
            "siteActive": True,
            "siteInMaintenance": False,
            "validated": True,
            "thirdParty": False,
            "operatedBy": "FAA",
            "siteId": 47,
            "siteName": "Summit",
            "cameras": [
                {
                    "cameraId": 10758,
                    "cameraDirection": "NorthWest",
                    "cameraBearing": 320,
                    "cameraLastSuccess": current,
                    "cameraInMaintenance": False,
                    "cameraOutOfOrder": False,
                    "mapWedgeAngle": 45,
                    "latitude": 63.3,
                    "longitude": -149.1,
                },
                {
                    "cameraId": 10759,
                    "cameraDirection": "South",
                    "cameraBearing": 180,
                    "cameraLastSuccess": stale,
                    "cameraInMaintenance": False,
                    "cameraOutOfOrder": False,
                    "mapWedgeAngle": 45,
                    "latitude": 63.3,
                    "longitude": -149.1,
                },
            ],
        }

        cameras = faa_cameras(lambda _url: {"payload": [site]})

        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0].azimuth_degrees, 320)
        self.assertEqual(cameras[0].bearing_tolerance_degrees, 22.5)
        self.assertTrue(cameras[0].url.endswith("/details/camera/10758"))

    def test_faa_imports_recent_nav_canada_views(self) -> None:
        now = datetime.now(UTC).isoformat()
        site = {
            "country": "CA",
            "siteActive": True,
            "siteInMaintenance": False,
            "validated": False,
            "thirdParty": True,
            "operatedBy": "NAV CANADA",
            "siteId": 306,
            "siteName": "Merritt",
            "cameras": [
                {
                    "cameraId": 11036,
                    "cameraDirection": "SouthWest",
                    "cameraBearing": 243,
                    "cameraLastSuccess": now,
                    "cameraInMaintenance": False,
                    "cameraOutOfOrder": False,
                    "mapWedgeAngle": 45,
                    "latitude": 50.12278,
                    "longitude": -120.74722,
                }
            ],
        }

        cameras = faa_cameras(lambda _url: {"payload": [site]})

        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0].operated_by, "NAV CANADA")
        self.assertEqual(cameras[0].azimuth_degrees, 243)
        self.assertEqual(cameras[0].bearing_tolerance_degrees, 22.5)
        self.assertEqual(cameras[0].camera_id, 11036)

        unvalidated_us = site | {"country": "US"}
        self.assertEqual(faa_cameras(lambda _url: {"payload": [unvalidated_us]}), [])
        other_operator = site | {"operatedBy": "Other"}
        self.assertEqual(faa_cameras(lambda _url: {"payload": [other_operator]}), [])


if __name__ == "__main__":
    unittest.main()
