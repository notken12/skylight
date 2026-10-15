import sqlite3
import unittest
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from backend.test_weather_database import sample_data
from backend.weather_database import initialize, save_run, source_rows
from backend.weather_queries import event_history, list_runs, read_run_map
from backend.weather_storage import compact_json


def save_sample(root: Path, at: datetime, suffix: str, data: dict | None = None) -> int:
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    (assets / f"band-{suffix}.png").write_bytes(b"band")
    (assets / f"quality-{suffix}.png").write_bytes(b"quality")
    return save_run(
        root / "weather.sqlite3",
        sample_data(at, suffix) if data is None else data,
        None,
        at,
        assets,
        perf_counter(),
    )


def create_legacy_database(path: Path, at: datetime) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            (Path(__file__).parent / "fixtures/weather_v1.sql").read_text()
        )
        connection.execute(
            "INSERT INTO camera_catalogs VALUES (1, 'catalog', ?)",
            (zlib.compress(compact_json([]).encode()),),
        )
        for run_id in (1, 2):
            data = sample_data(at, str(run_id))
            observed = at.isoformat(timespec="seconds")
            connection.execute(
                """INSERT INTO runs VALUES
                   (?, ?, NULL, ?, ?, '1', 1, 0, ?, ?, NULL, ?, 1)""",
                (
                    run_id,
                    f"slot-{run_id}",
                    observed,
                    observed,
                    compact_json(data["metadata"]),
                    compact_json(data["sunset"]),
                    compact_json(data["clouds"]),
                ),
            )
            connection.executemany(
                "INSERT INTO run_sources VALUES (?, ?, ?, ?, ?)",
                source_rows(data, run_id),
            )
            if run_id == 1:
                connection.executemany(
                    "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            1,
                            "storm",
                            "NOAA ProbSevere v3",
                            "storm-1",
                            observed,
                            observed,
                        ),
                        (2, "cloud_patch", "DWD ICON", "40:-100", observed, observed),
                    ],
                )
            for event_id, feature in (
                (1, data["storms"]["features"][0]),
                (2, data["clouds"]["features"]["features"][0]),
            ):
                sample_id = (run_id - 1) * 2 + event_id
                connection.execute(
                    """INSERT INTO event_samples VALUES
                       (?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)""",
                    (
                        sample_id,
                        event_id,
                        run_id,
                        observed,
                        45 if event_id == 1 else 50,
                        compact_json(feature),
                    ),
                )
                if event_id == 2:
                    connection.execute(
                        "INSERT INTO cloud_patch_metrics VALUES (?, 2, 3, 40)",
                        (sample_id,),
                    )


class WeatherStorageTests(unittest.TestCase):
    def test_forecast_sharing_and_latest_only_geometry(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            at = datetime(2026, 10, 1, tzinfo=UTC)
            first_data = sample_data(at, "first")
            first = save_sample(root, at, "first", first_data)
            later = at + timedelta(minutes=10)
            second_data = sample_data(later, "second")
            second_data["clouds"] = first_data["clouds"]
            second_data["sunset"]["forecast_time"] = first_data["clouds"][
                "forecast_time"
            ]
            second = save_sample(root, later, "second", second_data)
            database = root / "weather.sqlite3"
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM cloud_forecasts"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM cloud_patch_metrics"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT DISTINCT run_id FROM latest_forecast_features"
                    ).fetchall(),
                    [(second,)],
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM event_samples WHERE cloud_forecast_id IS NOT NULL AND feature_json IS NOT NULL"
                    ).fetchone()[0],
                    0,
                )
            old_map = read_run_map(database, first)
            latest = read_run_map(database, second)
            assert old_map is not None and latest is not None
            self.assertEqual([event["kind"] for event in old_map["events"]], ["storm"])
            self.assertEqual(len(latest["events"]), 2)
            self.assertTrue(latest["run"]["forecast_geojson_available"])
            cloud = next(
                event for event in latest["events"] if event["kind"] == "cloud_patch"
            )
            history = event_history(database, cloud["event_id"])
            assert history is not None
            self.assertEqual(len(history["samples"]), 1)
            self.assertEqual(history["samples"][0]["run_id"], second)
            self.assertEqual(
                [run["event_count"] for run in list_runs(database, 10)], [2, 2]
            )

    def test_retention_boundary_and_shared_assets(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            at = datetime(2026, 10, 1, tzinfo=UTC)
            first_data = sample_data(at, "first")
            first = save_sample(root, at, "first", first_data)
            second_data = sample_data(at + timedelta(days=1), "second")
            second_data["clouds"] = first_data["clouds"]
            second_data["sunset"]["forecast_time"] = first_data["clouds"][
                "forecast_time"
            ]
            second = save_sample(root, at + timedelta(days=1), "second", second_data)
            frames = root / "assets/frames"
            frames.mkdir()
            frame = frames / "shared.jpg"
            frame.write_bytes(b"shared")
            database = root / "weather.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE camera_samples SET archived_url = '/assets/frames/shared.jpg'"
                )
                shared_forecast = connection.execute(
                    "SELECT cloud_forecast_id FROM runs WHERE id = ?", (first,)
                ).fetchone()[0]
            newest = save_sample(root, at + timedelta(days=11), "newest")
            self.assertEqual(
                [run["id"] for run in list_runs(database, 10)], [newest, second]
            )
            self.assertIsNone(read_run_map(database, first))
            self.assertFalse((root / "assets/band-first.png").exists())
            self.assertTrue((root / "assets/band-second.png").exists())
            self.assertTrue(frame.exists())
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM cloud_forecasts WHERE id = ?",
                        (shared_forecast,),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_check").fetchall(), []
                )
            save_sample(root, at + timedelta(days=11, minutes=1), "after-boundary")
            self.assertIsNone(read_run_map(database, second))
            self.assertFalse(frame.exists())
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM cloud_forecasts WHERE id = ?",
                        (shared_forecast,),
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_check").fetchall(), []
                )

    def test_failed_collection_preserves_latest_cache(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            at = datetime(2026, 10, 1, tzinfo=UTC)
            first = save_sample(root, at, "first")
            data = sample_data(at + timedelta(minutes=10), "missing")
            with self.assertRaises(FileNotFoundError):
                save_run(
                    root / "weather.sqlite3",
                    data,
                    None,
                    None,
                    root / "assets",
                    perf_counter(),
                )
            latest = read_run_map(root / "weather.sqlite3", first)
            assert latest is not None
            self.assertEqual(len(latest["events"]), 2)
            self.assertEqual(len(list_runs(root / "weather.sqlite3", 10)), 1)

    def test_legacy_migration_preserves_ids_and_shares_forecasts(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "weather.sqlite3"
            create_legacy_database(database, datetime(2026, 10, 1, tzinfo=UTC))
            initialize(database)
            initialize(database)
            latest = read_run_map(database, 2)
            old = read_run_map(database, 1)
            assert latest is not None and old is not None
            self.assertEqual([event["id"] for event in old["events"]], [1])
            self.assertEqual({event["id"] for event in latest["events"]}, {2, 3})
            self.assertEqual(
                [run["event_count"] for run in list_runs(database, 10)], [2, 2]
            )
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM cloud_patch_metrics"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_check").fetchall(), []
                )

    def test_cloud_insert_batches(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            at = datetime(2026, 10, 1, tzinfo=UTC)
            data = sample_data(at, "batch")
            feature = data["clouds"]["features"]["features"][0]
            data["clouds"]["features"]["features"] = [
                feature | {"properties": feature["properties"] | {"id": str(index)}}
                for index in range(501)
            ]
            run_id = save_sample(root, at, "batch", data)
            result = read_run_map(root / "weather.sqlite3", run_id)
            assert result is not None
            self.assertEqual(len(result["events"]), 502)
