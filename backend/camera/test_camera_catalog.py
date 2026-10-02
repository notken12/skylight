import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from threading import Barrier
from unittest.mock import Mock, call, patch

from backend import weather_source
from backend.camera.camera_models import Camera
from backend.camera.cameras import (
    ALERTWEST_CAMERAS_URL,
    AURORAMAX_IMAGE_URL,
    FAA_CAMERAS_URL,
    IOWA_QUERY_URL,
    UCALGARY_OBSERVATORIES_URL,
    UCALGARY_STREAMS_URL,
    USGS_CAMERAS_URL,
    CameraCatalog,
    CameraDatabase,
    get_camera_database,
    load_camera_database,
)


class CameraCatalogTests(unittest.TestCase):
    def test_provider_ids_are_scoped_to_their_network(self) -> None:
        first = Camera("First", "North", 40, -100, "first", provider_id="1")
        second = Camera("Second", "South", 41, -101, "second", provider_id="1")
        database = CameraDatabase(
            [CameraCatalog("First", [first]), CameraCatalog("Second", [second])]
        )

        self.assertIs(database.get_camera("First", "1"), first)
        self.assertIs(database.get_camera("Second", "1"), second)
        self.assertEqual(database.list_cameras("First"), [first])
        self.assertEqual(database.list_cameras(), [first, second])
        self.assertIsNone(database.get_camera("First", "missing"))
        self.assertIsNone(database.get_camera("Missing", "1"))
        self.assertEqual(database.list_cameras("Missing"), [])

    def test_catalog_does_not_change_when_lists_are_modified(self) -> None:
        camera = Camera("Test", "North", 40, -100, "test", provider_id="1")
        source = [camera]
        network = CameraCatalog("Test", source)
        networks = [network]
        database = CameraDatabase(networks)

        source.clear()
        networks.clear()
        network.list_cameras().clear()
        database.list_cameras().clear()
        database.list_cameras("Test").clear()

        self.assertEqual(network.list_cameras(), [camera])
        self.assertIs(network.get_camera("1"), camera)
        self.assertEqual(database.list_cameras(), [camera])
        self.assertIs(database.get_camera("Test", "1"), camera)

    def test_invalid_camera_identities_are_rejected(self) -> None:
        missing_id = Camera("Test", "North", 40, -100, "test")
        duplicate = Camera("Test", "North", 40, -100, "test", provider_id="1")
        for cameras in ([missing_id], [duplicate, duplicate]):
            with self.subTest(cameras=cameras), self.assertRaises(ValueError):
                CameraCatalog("Test", cameras)

        with self.assertRaises(ValueError):
            CameraCatalog("Another", [duplicate])

    def test_duplicate_networks_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CameraDatabase([CameraCatalog("Test", []), CameraCatalog("Test", [])])

    def test_empty_catalogs_support_listing_and_missing_lookups(self) -> None:
        network = CameraCatalog("Test", [])
        database = CameraDatabase([])

        self.assertEqual(network.list_cameras(), [])
        self.assertIsNone(network.get_camera("missing"))
        self.assertEqual(database.list_cameras(), [])
        self.assertEqual(database.list_cameras("Test"), [])
        self.assertIsNone(database.get_camera("Test", "missing"))

    def test_loader_keeps_default_provider_selection_and_camera_order(self) -> None:
        responses = {
            ALERTWEST_CAMERAS_URL: [],
            USGS_CAMERAS_URL: [],
            IOWA_QUERY_URL: {"features": []},
            UCALGARY_STREAMS_URL: {"streams": []},
            UCALGARY_OBSERVATORIES_URL: [],
        }
        fetch_json = Mock(side_effect=lambda url: responses[url])
        fetch_faa_json = Mock(return_value={"payload": []})
        stale = datetime.now(UTC) - timedelta(hours=2)
        fetch_headers = Mock(
            return_value={"last-modified": format_datetime(stale, usegmt=True)}
        )

        database = load_camera_database(fetch_json, fetch_faa_json, fetch_headers)
        cameras = database.list_cameras()

        self.assertEqual(
            [camera.provider_id for camera in cameras],
            [
                "churchill-northern-lights",
                "poker-flat",
                "toolik-lake",
                "athabasca-auroracam",
            ],
        )
        fetch_json.assert_has_calls([call(url) for url in responses], any_order=True)
        self.assertEqual(fetch_json.call_count, len(responses))
        fetch_faa_json.assert_called_once_with(FAA_CAMERAS_URL)
        fetch_headers.assert_called_once_with(AURORAMAX_IMAGE_URL)

    def test_singleton_initializes_once_under_concurrent_access(self) -> None:
        database = CameraDatabase([CameraCatalog("Test", [])])
        barrier = Barrier(8)

        def get_database() -> CameraDatabase:
            barrier.wait(timeout=5)
            return get_camera_database()

        with (
            patch("backend.camera.cameras._camera_database", None),
            patch(
                "backend.camera.cameras.load_camera_database", return_value=database
            ) as load_database,
            ThreadPoolExecutor(max_workers=8) as executor,
        ):
            futures = [executor.submit(get_database) for _ in range(8)]
            for future in futures:
                self.assertIs(future.result(timeout=5), database)
            self.assertIs(get_camera_database(), database)
            load_database.assert_called_once_with(
                weather_source.fetch_json,
                weather_source.fetch_faa_json,
                weather_source.fetch_headers,
            )

    def test_singleton_initialization_errors_propagate(self) -> None:
        error = TimeoutError("provider timeout")
        with (
            patch("backend.camera.cameras._camera_database", None),
            patch("backend.camera.cameras.load_camera_database", side_effect=error),
            self.assertRaises(TimeoutError) as raised,
        ):
            get_camera_database()
        self.assertIs(raised.exception, error)


if __name__ == "__main__":
    unittest.main()
