import sqlite3
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from backend.weather_database import initialize, save_run
from backend.weather_queries import event_history, list_runs, read_run_map, run_for_slot


def sample_data(at: datetime, suffix: str) -> dict:
    observed = at.isoformat(timespec="seconds")
    storm = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-100, 40], [-99, 40], [-99, 41], [-100, 40]]],
        },
        "properties": {
            "id": "storm-1",
            "circle": {
                "center_latitude": 40.3,
                "center_longitude": -99.7,
                "radius_km": 10,
            },
            "view_circle": {
                "center_latitude": 40.3,
                "center_longitude": -99.7,
                "radius_km": 50,
            },
            "interestingness": {"score": 45},
            "probability": 60,
            "hail_probability": 20,
            "wind_probability": 30,
            "tornado_probability": 5,
            "flashes_5min": 10,
            "reflectivity_dbz": 55,
            "outline_shape": {
                "score": 30,
                "jaggedness": 0.2,
                "nonconvexity": 0.3,
                "fragmentation": 0,
                "component_count": 1,
            },
        },
    }
    cloud = {
        "type": "Feature",
        "geometry": storm["geometry"],
        "properties": {
            "id": "40:-100",
            "score": 50,
            "horizontal_variation": 2,
            "vertical_variation": 3,
            "peak_cloud_fraction": 40,
        },
    }
    camera = {
        "network": "FAA WeatherCams",
        "provider_id": "1",
        "name": "Storm camera",
        "latitude": 40,
        "longitude": -100,
        "url": "https://example.com/camera/1",
        "event_ids": ["storm-1"],
        "aurora_event_ids": [],
        "sunset_score": 0,
        "sunset_band": False,
        "aurora_cloud_cover_percent": None,
        "aurora_dark": False,
        "sharpness": 40,
        "image_scores": {"warm_tone_strength": 0.2},
        "view_score": {
            "margin": 0.1,
            "threshold": 0.06,
            "accepted": True,
            "storm_similarity": 0.3,
            "rejected_similarity": 0.2,
            "scenic_similarity": 0.18,
            "poor_similarity": 0.22,
        },
        "sunset_view_score": None,
        "rank": {
            "score": 40,
            "sharpness_score": 50,
            "sharpness_contribution": 10,
            "components": {},
        },
        "frame": {
            "captured_at": observed,
            "image_url": f"https://example.com/frame-{suffix}.jpg",
        },
    }
    background = camera | {
        "provider_id": "2",
        "name": "Background camera",
        "event_ids": [],
        "sharpness": None,
        "image_scores": None,
        "view_score": None,
        "rank": None,
        "frame": None,
    }
    return {
        "storms": {"features": [storm]},
        "clouds": {
            "features": {"features": [cloud]},
            "forecast_time": observed,
            "source_url": "https://example.com/icon",
            "tile_degrees": 1.5,
        },
        "auroras": None,
        "sunset": {
            "map_time": observed,
            "forecast_time": observed,
            "source_url": "https://example.com/icon",
            "band_url": f"/assets/band-{suffix}.png",
            "quality_url": f"/assets/quality-{suffix}.png",
            "camera_in_band": [False, False],
            "camera_scores": [0, 0],
        },
        "metadata": {
            "generated_time": observed,
            "valid_time": observed,
            "source_url": "https://example.com/probsevere",
            "visual_model": "clip-v1",
            "visual_scorer_version": "clip-v1/references-v1",
            "blur_threshold": "30",
            "sunset_minimum_score": "10",
        },
        "cameras": [camera, background],
    }


class WeatherDatabaseTests(unittest.TestCase):
    def test_run_history_and_camera_scores(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            database = root / "weather.sqlite3"
            first = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
            run_ids = []
            for index, at in enumerate((first, first + timedelta(minutes=5))):
                suffix = str(index)
                (assets / f"band-{suffix}.png").write_bytes(b"band")
                (assets / f"quality-{suffix}.png").write_bytes(b"quality")
                run_ids.append(
                    save_run(
                        database,
                        sample_data(at, suffix),
                        None,
                        at,
                        assets,
                        {("FAA WeatherCams", "1"): "/assets/frames/saved.jpg"},
                        perf_counter() - 2,
                    )
                )
            data = read_run_map(database, run_ids[0])
            assert data is not None
            self.assertEqual(len(data["events"]), 2)
            self.assertGreaterEqual(data["run"]["duration_seconds"], 2)
            self.assertEqual(len(data["cameras"]), 2)
            self.assertIsNone(data["cameras"][1]["sample"])
            sample = data["cameras"][0]["sample"]
            self.assertEqual(sample["archived_url"], "/assets/frames/saved.jpg")
            self.assertEqual(sample["scores"]["sharpness"]["value"], 40)
            self.assertEqual(sample["scores"]["warm_tone"]["value"], 0.2)
            self.assertTrue(sample["scores"]["storm_view"]["passed"])
            self.assertEqual(len(sample["event_sample_ids"]), 1)
            history = event_history(database, data["events"][0]["event_id"])
            assert history is not None
            self.assertEqual(len(history["samples"]), 2)
            self.assertEqual(
                [row["id"] for row in list_runs(database, 10)], run_ids[::-1]
            )
            self.assertGreaterEqual(list_runs(database, 10)[0]["duration_seconds"], 2)
            self.assertEqual(
                run_for_slot(database, first.isoformat(timespec="minutes")), run_ids[0]
            )
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM camera_samples"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM camera_catalogs"
                    ).fetchone()[0],
                    1,
                )
            (assets / "band-later.png").write_bytes(b"band")
            (assets / "quality-later.png").write_bytes(b"quality")
            later_id = save_run(
                database,
                sample_data(first + timedelta(hours=1), "later"),
                None,
                None,
                assets,
                {},
                perf_counter(),
            )
            later = read_run_map(database, later_id)
            assert later is not None
            self.assertNotEqual(
                later["events"][0]["event_id"], data["events"][0]["event_id"]
            )

    def test_frames_without_capture_times_keep_their_urls(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            (assets / "band-unknown.png").write_bytes(b"band")
            (assets / "quality-unknown.png").write_bytes(b"quality")
            at = datetime(2026, 10, 1, 12, tzinfo=UTC)
            data = sample_data(at, "unknown")
            data["cameras"][0]["frame"]["captured_at"] = None
            database = root / "weather.sqlite3"
            run_id = save_run(database, data, None, at, assets, {}, perf_counter())
            saved = read_run_map(database, run_id)
            assert saved is not None
            sample = saved["cameras"][0]["sample"]
            self.assertIsNone(sample["captured_at_utc"])
            self.assertEqual(
                sample["frame_url"], "https://example.com/frame-unknown.jpg"
            )

    def test_aurora_event_and_candidate_scores(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            (assets / "band-aurora.png").write_bytes(b"band")
            (assets / "quality-aurora.png").write_bytes(b"quality")
            at = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
            data = sample_data(at, "aurora")
            feature = {
                "type": "Feature",
                "geometry": data["storms"]["features"][0]["geometry"],
                "properties": {
                    "id": "aurora-1",
                    "circle": {
                        "center_latitude": 40.3,
                        "center_longitude": -99.7,
                        "radius_km": 10,
                    },
                    "view_circle": {
                        "center_latitude": 40.3,
                        "center_longitude": -99.7,
                        "radius_km": 10,
                    },
                    "interestingness": {"score": 35},
                    "aurora_percent": 50,
                    "cloud_cover_percent": 30,
                },
            }
            data["auroras"] = {
                "features": {"features": [feature]},
                "cameras": [],
                "observation_time": at.isoformat(),
                "forecast_time": at.isoformat(),
                "cloud_time": at.isoformat(),
                "cloud_source_url": "https://example.com/gfs",
            }
            data["cameras"][0]["aurora_event_ids"] = ["aurora-1"]
            data["cameras"][0]["aurora_cloud_cover_percent"] = 20
            data["cameras"][0]["aurora_dark"] = True
            database = root / "weather.sqlite3"
            run_id = save_run(database, data, None, None, assets, {}, perf_counter())
            saved = read_run_map(database, run_id)
            assert saved is not None
            auroras = [event for event in saved["events"] if event["kind"] == "aurora"]
            self.assertEqual(len(auroras), 1)
            scores = saved["cameras"][0]["sample"]["scores"]
            self.assertEqual(scores["aurora_cloud_cover"]["value"], 20)
            self.assertEqual(scores["aurora_dark"]["value"], 1)

    def test_existing_database_adds_run_duration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "weather.sqlite3"
            assets = root / "assets"
            assets.mkdir()
            (assets / "band-old.png").write_bytes(b"band")
            (assets / "quality-old.png").write_bytes(b"quality")
            at = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
            run_id = save_run(
                database, sample_data(at, "old"), None, None, assets, {}, perf_counter()
            )
            with sqlite3.connect(database) as connection:
                connection.execute("ALTER TABLE runs DROP COLUMN duration_seconds")
            initialize(database)
            with sqlite3.connect(database) as connection:
                duration = connection.execute(
                    "SELECT duration_seconds FROM runs WHERE id = ?", (run_id,)
                ).fetchone()[0]
            self.assertIsNone(duration)


if __name__ == "__main__":
    unittest.main()
