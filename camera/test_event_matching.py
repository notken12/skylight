import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

from camera.camera_matching import match_cameras
from camera.cameras import (
    AURORAMAX_IMAGE_URL,
    UCALGARY_LATEST_URL,
    UCALGARY_OBSERVATORIES_URL,
    Camera,
    auroramax_cameras,
    faa_cameras,
    ucalgary_aurora_cameras,
)


class EventMatchingTests(unittest.TestCase):
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

    def test_all_sky_camera_matches_aurora_without_direction(self) -> None:
        events = {
            "features": [
                {
                    "properties": {
                        "id": "aurora-a",
                        "view_circle": {
                            "center_latitude": 60.0,
                            "center_longitude": -112.0,
                            "radius_km": 50.0,
                        },
                    }
                }
            ]
        }
        camera = Camera(
            "UCalgary TREx RGB",
            "Fort Smith",
            60.03,
            -111.93,
            "https://example.com/live",
            sky_facing=True,
        )

        self.assertEqual(match_cameras(events, [camera])[0].event_ids, ())
        self.assertEqual(
            match_cameras(events, [camera], include_sky_facing=True)[0].event_ids,
            ("aurora-a",),
        )

    def test_live_aurora_sources_keep_only_recent_images(self) -> None:
        recent = datetime.now(UTC).replace(microsecond=0)
        stale = recent - timedelta(hours=2)
        streams = [
            {
                "id": "trexrgb_fsmi_standard",
                "site_uid": "fsmi",
                "mimetype": "image/jpeg",
            },
            {
                "id": "trexrgb_gill_standard",
                "site_uid": "gill",
                "mimetype": "image/jpeg",
            },
        ]
        observatories = [
            {
                "uid": "fsmi",
                "full_name": "Fort Smith, NWT, Canada",
                "geodetic_latitude": 60.03,
                "geodetic_longitude": -111.93,
            },
            {
                "uid": "gill",
                "full_name": "Gillam, MB, Canada",
                "geodetic_latitude": 56.38,
                "geodetic_longitude": -94.64,
            },
        ]

        def fetch_json(url: str) -> Any:
            if url == UCALGARY_OBSERVATORIES_URL:
                return observatories
            return {"streams": streams}

        def fetch_headers(url: str) -> dict[str, str]:
            time = (
                recent
                if url == UCALGARY_LATEST_URL.format(id=streams[0]["id"])
                else stale
            )
            return {"x-rt-stream-last-updated-utc": time.isoformat()}

        cameras = ucalgary_aurora_cameras(fetch_json, fetch_headers)

        self.assertEqual(len(cameras), 1)
        self.assertTrue(cameras[0].sky_facing)
        self.assertEqual(cameras[0].name, "Fort Smith, NWT, Canada · all sky")
        self.assertEqual(cameras[0].view_time, recent.isoformat())
        self.assertEqual(
            cameras[0].snapshot_url,
            f"{UCALGARY_LATEST_URL.format(id=streams[0]['id'])}?at={int(recent.timestamp())}",
        )

        auroramax = auroramax_cameras(
            lambda url: (
                {"last-modified": format_datetime(recent, usegmt=True)}
                if url == AURORAMAX_IMAGE_URL
                else {}
            )
        )
        self.assertEqual(len(auroramax), 1)
        self.assertTrue(auroramax[0].sky_facing)

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
