import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from fastapi.testclient import TestClient

from backend.api_server import create_app
from backend.camera.faa_snapshots import fetch_latest_image


class LiveCameraImagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.fetch_json = Mock()
        self.client = TestClient(
            create_app(root / "weather.sqlite3", root / "assets", root, self.fetch_json)
        )
        self.addCleanup(self.client.close)

    def test_latest_image_uses_fresh_provider_metadata(self) -> None:
        now = datetime.now(UTC)
        newest = {
            "imageUri": "https://images.example/latest.jpg",
            "imageDatetime": (now - timedelta(seconds=10)).isoformat(),
        }
        self.fetch_json.return_value = {
            "payload": [
                newest,
                {
                    "imageUri": "old.jpg",
                    "imageDatetime": (now - timedelta(hours=1)).isoformat(),
                },
                {
                    "imageUri": "future.jpg",
                    "imageDatetime": (now + timedelta(hours=1)).isoformat(),
                },
            ]
        }
        response = self.client.get("/api/cameras/FAA%20WeatherCams/42/latest_image")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "image_url": newest["imageUri"],
                "captured_at_utc": newest["imageDatetime"],
            },
        )
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.fetch_json.assert_called_once_with(
            "https://weathercams.faa.gov/api/cameras/42/images/last/24"
        )
        self.fetch_json.return_value = {
            "payload": [
                {
                    "imageUri": "https://images.example/next.jpg",
                    "imageDatetime": now.isoformat(),
                }
            ]
        }
        updated = self.client.get("/api/cameras/FAA%20WeatherCams/42/latest_image")
        self.assertEqual(updated.json()["image_url"], "https://images.example/next.jpg")

    def test_missing_image_returns_not_found(self) -> None:
        self.fetch_json.return_value = {"payload": []}
        response = self.client.get("/api/cameras/FAA%20WeatherCams/42/latest_image")
        self.assertEqual(response.status_code, 404)

    def test_other_networks_and_invalid_ids_do_not_fetch(self) -> None:
        for path, status in (
            ("ALERTWest/42", 404),
            ("FAA%20WeatherCams/0", 422),
            ("FAA%20WeatherCams/not-a-number", 422),
        ):
            response = self.client.get(f"/api/cameras/{path}/latest_image")
            self.assertEqual(response.status_code, status)
        self.fetch_json.assert_not_called()

    def test_snapshot_collector_still_rejects_missing_images(self) -> None:
        self.fetch_json.return_value = {"payload": []}
        with self.assertRaisesRegex(ValueError, "No FAA camera image"):
            fetch_latest_image(42, datetime.now(UTC), self.fetch_json)
