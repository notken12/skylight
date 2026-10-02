import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from backend.camera.camera_models import CameraSnapshot
from backend.camera.cameras import (
    AURORAMAX_FEED_URL,
    AURORAMAX_IMAGE_URL,
    UCALGARY_LATEST_URL,
    AlertWestNetwork,
    AthabascaAuroraCamNetwork,
    AuroraMAXNetwork,
    CameraDatabase,
    CameraNetwork,
    ExploreNetwork,
    FAANetwork,
    IowaMesonetNetwork,
    MarylandCHARTNetwork,
    NebraskaDOTNetwork,
    UAFAllskyNetwork,
    UCalgaryTRExNetwork,
    USGSNetwork,
    WashingtonDOTNetwork,
)
from backend.camera.faa_snapshots import FAA_REFERER
from backend.weather_source import HttpResponse, fetch_response


class LatestSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        self.new = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        self.fetch_image = Mock(return_value=HttpResponse(b"fresh image", {}))

    def assert_snapshot(
        self, snapshot: CameraSnapshot, url: str, captured_at: str | None
    ) -> None:
        self.assertEqual(snapshot.image, b"fresh image")
        self.assertEqual(snapshot.image_url, url)
        self.assertEqual(snapshot.captured_at, captured_at)

    def test_alertwest_refreshes_metadata_without_changing_catalog(self) -> None:
        record = {
            "site": {"id": "1", "latitude": 40, "longitude": -100},
            "name": "North",
            "position": {"pan": "10"},
            "image": {"time": self.old, "url": "old.jpg"},
        }
        metadata = Mock(
            side_effect=[
                [record],
                [record | {"image": {"time": self.new, "url": "new.jpg"}}],
                [record | {"image": {"time": None, "url": None}}],
                [],
            ]
        )
        network = AlertWestNetwork(metadata, self.fetch_image)
        camera = network.get_camera("1")
        assert camera is not None
        self.assert_snapshot(network.fetch_latest_snapshot("1"), "new.jpg", self.new)
        self.fetch_image.assert_called_once_with("new.jpg", None)
        self.assertIs(network.get_camera("1"), camera)
        self.assertEqual(camera.view_time, self.old)
        for _ in range(2):
            with self.assertRaises(ValueError):
                network.fetch_latest_snapshot("1")
        self.assertEqual(self.fetch_image.call_count, 1)

    def test_usgs_selects_one_immutable_image_and_preserves_capture_time(self) -> None:
        metadata = Mock(
            side_effect=[
                [
                    {
                        "camId": "river/a",
                        "camName": "River",
                        "hideCam": False,
                        "newestImageDT": self.old,
                        "lat": 40,
                        "lng": -100,
                        "smallDir": "https://example.com/720/",
                    }
                ],
                [{"filename": "dated.jpg", "timestamp": "2026-10-01T12-00-02Z"}],
                [],
            ]
        )
        network = USGSNetwork(metadata, self.fetch_image)
        self.assert_snapshot(
            network.fetch_latest_snapshot("river/a"),
            "https://example.com/720/dated.jpg",
            "2026-10-01T12:00:02+00:00",
        )
        query = parse_qs(urlsplit(metadata.call_args.args[0]).query)
        self.assertEqual(
            query,
            {
                "camId": ["river/a"],
                "limit": ["1"],
                "recent": ["true"],
                "rawItem": ["true"],
            },
        )
        with self.assertRaises(ValueError):
            network.fetch_latest_snapshot("river/a")
        self.fetch_image.assert_called_once_with(
            "https://example.com/720/dated.jpg", None
        )

    def test_faa_selects_latest_frame_and_uses_required_referer(self) -> None:
        site = {
            "country": "US",
            "siteActive": True,
            "siteInMaintenance": False,
            "validated": True,
            "siteName": "North",
            "siteId": 1,
            "operatedBy": "FAA",
            "cameras": [
                {
                    "cameraId": 12,
                    "cameraLastSuccess": self.old,
                    "cameraInMaintenance": False,
                    "cameraOutOfOrder": False,
                    "cameraDirection": "N",
                    "cameraBearing": 0,
                    "latitude": 40,
                    "longitude": -100,
                    "mapWedgeAngle": 40,
                }
            ],
        }
        metadata = Mock(
            side_effect=[
                {"payload": [site]},
                {
                    "payload": [
                        {"imageDatetime": self.new, "imageUri": "new.jpg"},
                        {"imageDatetime": self.old, "imageUri": "old.jpg"},
                        {
                            "imageDatetime": "2100-01-01T00:00:00Z",
                            "imageUri": "future.jpg",
                        },
                    ]
                },
            ]
        )
        network = FAANetwork(metadata, self.fetch_image)
        self.assert_snapshot(network.fetch_latest_snapshot("12"), "new.jpg", self.new)
        metadata.assert_called_with(
            "https://weathercams.faa.gov/api/cameras/12/images/last/24"
        )
        self.fetch_image.assert_called_once_with("new.jpg", FAA_REFERER)

    def test_iowa_refreshes_dated_image_metadata(self) -> None:
        feature = {
            "geometry": {"coordinates": [-100, 40]},
            "properties": {
                "cid": "KCCI-036",
                "name": "North",
                "angle": 0,
                "url": "old.jpg",
                "valid": self.old,
            },
        }
        updated = feature | {
            "properties": feature["properties"] | {"url": "new.jpg", "valid": self.new}
        }
        metadata = Mock(
            side_effect=[
                {"features": [feature]},
                {"features": [updated]},
                {"features": []},
            ]
        )
        network = IowaMesonetNetwork(metadata, self.fetch_image)
        self.assert_snapshot(
            network.fetch_latest_snapshot("KCCI-036"), "new.jpg", self.new
        )
        self.fetch_image.assert_called_once_with("new.jpg", None)
        with self.assertRaises(ValueError):
            network.fetch_latest_snapshot("KCCI-036")

    def test_trex_timestamp_comes_from_the_downloaded_image_response(self) -> None:
        metadata = Mock(
            side_effect=[
                {
                    "streams": [
                        {"id": "stream", "mimetype": "image/jpeg", "site_uid": "site"}
                    ]
                },
                [
                    {
                        "uid": "site",
                        "full_name": "North",
                        "geodetic_latitude": 60,
                        "geodetic_longitude": -100,
                    }
                ],
            ]
        )
        headers = Mock(return_value={"x-rt-stream-last-updated-utc": self.old})
        self.fetch_image.return_value = HttpResponse(
            b"fresh image", {"x-rt-stream-last-updated-utc": self.new}
        )
        network = UCalgaryTRExNetwork(metadata, headers, self.fetch_image)
        url = UCALGARY_LATEST_URL.format(id="stream")
        self.assert_snapshot(network.fetch_latest_snapshot("stream"), url, self.new)
        self.fetch_image.assert_called_once_with(url, None)
        self.assertEqual(headers.call_count, 1)

    def test_auroramax_timestamp_comes_from_the_downloaded_image_response(self) -> None:
        old = datetime.fromisoformat(self.old).replace(microsecond=0)
        new = datetime.fromisoformat(self.new).replace(microsecond=0)
        headers = Mock(
            return_value={"last-modified": format_datetime(old, usegmt=True)}
        )
        self.fetch_image.return_value = HttpResponse(
            b"fresh image", {"last-modified": format_datetime(new, usegmt=True)}
        )
        network = AuroraMAXNetwork(headers, self.fetch_image)
        self.assert_snapshot(
            network.fetch_latest_snapshot(AURORAMAX_FEED_URL),
            AURORAMAX_IMAGE_URL,
            new.isoformat(),
        )
        self.fetch_image.assert_called_once_with(AURORAMAX_IMAGE_URL, None)
        self.assertEqual(headers.call_count, 1)

    def test_traffic_feeds_download_images_without_inventing_capture_times(
        self,
    ) -> None:
        feature = {
            "geometry": {"coordinates": [-100, 40]},
            "properties": {
                "OBJECTID": 1,
                "CameraTitle": "North",
                "ImageURL": "live.jpg",
                "CompassDirection": "N",
                "name": "North",
                "PhotoURL": "live.jpg",
            },
        }
        networks: list[CameraNetwork] = [
            WashingtonDOTNetwork(
                Mock(return_value={"features": [feature]}), self.fetch_image
            ),
            NebraskaDOTNetwork(
                Mock(return_value={"features": [feature]}), self.fetch_image
            ),
            MarylandCHARTNetwork(
                Mock(
                    return_value=[
                        {
                            "url": "live.jpg",
                            "location": "North",
                            "the_geom": feature["geometry"],
                        }
                    ]
                ),
                self.fetch_image,
            ),
        ]
        for network in networks:
            with self.subTest(network=network.name):
                camera = network.list_cameras()[0]
                assert camera.provider_id is not None
                self.assert_snapshot(
                    network.fetch_latest_snapshot(camera.provider_id), "live.jpg", None
                )
        self.assertEqual(self.fetch_image.call_count, 3)

    def test_unknown_ids_fail_before_network_io(self) -> None:
        metadata = Mock(return_value={"features": []})
        network = IowaMesonetNetwork(metadata, self.fetch_image)
        database = CameraDatabase([network])
        with self.assertRaises(KeyError):
            database.fetch_latest_snapshot("Iowa Mesonet", "missing")
        with self.assertRaises(KeyError):
            database.fetch_latest_snapshot("missing", "1")
        self.assertEqual(metadata.call_count, 1)
        self.fetch_image.assert_not_called()

    def test_link_only_networks_explicitly_reject_snapshots(self) -> None:
        networks: list[CameraNetwork] = [
            ExploreNetwork(),
            UAFAllskyNetwork(),
            AthabascaAuroraCamNetwork(),
        ]
        database = CameraDatabase(networks)
        for network in networks:
            for camera in network.list_cameras():
                assert camera.provider_id is not None
                with (
                    self.subTest(camera=camera.name),
                    self.assertRaises(NotImplementedError),
                ):
                    database.fetch_latest_snapshot(network.name, camera.provider_id)

    def test_provider_errors_propagate(self) -> None:
        network = MarylandCHARTNetwork(
            Mock(
                return_value=[
                    {
                        "url": "live.jpg",
                        "location": "North",
                        "the_geom": {"coordinates": [-100, 40]},
                    }
                ]
            ),
            self.fetch_image,
        )
        error = TimeoutError("provider timeout")
        self.fetch_image.side_effect = error
        with self.assertRaises(TimeoutError) as raised:
            network.fetch_latest_snapshot("live.jpg")
        self.assertIs(raised.exception, error)

    def test_http_transport_returns_body_and_headers_from_one_response(self) -> None:
        response = Mock()
        response.read.return_value = b"frame"
        response.headers = {"X-RT-Stream-Last-Updated-UTC": self.new}
        with patch("backend.weather_source.urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            fetched = fetch_response("https://example.com/frame.jpg", FAA_REFERER)
        self.assertEqual(
            fetched, HttpResponse(b"frame", {"x-rt-stream-last-updated-utc": self.new})
        )
        open_url.assert_called_once()
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("Referer"), FAA_REFERER)


if __name__ == "__main__":
    unittest.main()
