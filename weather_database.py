import hashlib
import json
import sqlite3
import zlib
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from phenomena.aurora.aurora import OVATION_URL
from weather_source import parse_utc_time

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS camera_catalogs (
    id INTEGER PRIMARY KEY,
    digest TEXT NOT NULL UNIQUE,
    camera_keys BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    slot_utc TEXT UNIQUE,
    requested_at_utc TEXT,
    generated_at_utc TEXT NOT NULL,
    map_at_utc TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    catalog_id INTEGER NOT NULL REFERENCES camera_catalogs(id),
    camera_count INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    sunset_json TEXT NOT NULL,
    aurora_json TEXT,
    clouds_json TEXT NOT NULL,
    duration_seconds REAL CHECK (duration_seconds >= 0)
);
CREATE INDEX IF NOT EXISTS runs_generated_idx ON runs(generated_at_utc DESC);
CREATE TABLE IF NOT EXISTS run_sources (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    observed_at_utc TEXT,
    forecast_valid_at_utc TEXT,
    PRIMARY KEY (run_id, source)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    first_seen_at_utc TEXT NOT NULL,
    last_seen_at_utc TEXT NOT NULL,
    UNIQUE (kind, source, source_id, first_seen_at_utc)
);
CREATE INDEX IF NOT EXISTS events_identity_idx
    ON events(kind, source, source_id, last_seen_at_utc DESC);
CREATE TABLE IF NOT EXISTS event_samples (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id),
    run_id INTEGER NOT NULL REFERENCES runs(id),
    valid_at_utc TEXT NOT NULL,
    center_lat REAL,
    center_lon REAL,
    core_radius_km REAL,
    view_radius_km REAL,
    interestingness REAL NOT NULL,
    feature_json TEXT NOT NULL,
    UNIQUE (event_id, run_id)
);
CREATE INDEX IF NOT EXISTS event_samples_run_idx
    ON event_samples(run_id, interestingness DESC);
CREATE INDEX IF NOT EXISTS event_samples_event_time_idx
    ON event_samples(event_id, valid_at_utc);
CREATE TABLE IF NOT EXISTS storm_metrics (
    sample_id INTEGER PRIMARY KEY REFERENCES event_samples(id),
    severe_probability REAL NOT NULL,
    hail_probability REAL NOT NULL,
    wind_probability REAL NOT NULL,
    tornado_probability REAL NOT NULL,
    flashes_5min INTEGER NOT NULL,
    reflectivity_dbz REAL NOT NULL,
    outline_complexity REAL NOT NULL,
    jaggedness REAL NOT NULL,
    nonconvexity REAL NOT NULL,
    fragmentation REAL NOT NULL,
    component_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS aurora_metrics (
    sample_id INTEGER PRIMARY KEY REFERENCES event_samples(id),
    aurora_percent REAL NOT NULL,
    cloud_cover_percent REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cloud_patch_metrics (
    sample_id INTEGER PRIMARY KEY REFERENCES event_samples(id),
    horizontal_variation REAL NOT NULL,
    vertical_variation REAL NOT NULL,
    peak_cloud_fraction REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cameras (
    network TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    catalog_json TEXT NOT NULL,
    PRIMARY KEY (network, provider_id)
);
CREATE TABLE IF NOT EXISTS camera_samples (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    network TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    camera_json TEXT NOT NULL,
    captured_at_utc TEXT,
    frame_url TEXT,
    archived_url TEXT,
    UNIQUE (run_id, network, provider_id),
    FOREIGN KEY (network, provider_id) REFERENCES cameras(network, provider_id)
);
CREATE INDEX IF NOT EXISTS camera_samples_history_idx
    ON camera_samples(network, provider_id, run_id DESC);
CREATE TABLE IF NOT EXISTS camera_event_matches (
    camera_sample_id INTEGER NOT NULL REFERENCES camera_samples(id),
    event_sample_id INTEGER NOT NULL REFERENCES event_samples(id),
    PRIMARY KEY (camera_sample_id, event_sample_id)
);
CREATE INDEX IF NOT EXISTS camera_event_matches_event_idx
    ON camera_event_matches(event_sample_id, camera_sample_id);
CREATE TABLE IF NOT EXISTS camera_view_scores (
    id INTEGER PRIMARY KEY,
    camera_sample_id INTEGER NOT NULL REFERENCES camera_samples(id),
    scorer_key TEXT NOT NULL,
    scorer_version TEXT NOT NULL,
    value REAL NOT NULL,
    threshold REAL,
    passed INTEGER CHECK (passed IN (0, 1)),
    UNIQUE (camera_sample_id, scorer_key)
);
CREATE TABLE IF NOT EXISTS camera_view_score_components (
    score_id INTEGER NOT NULL REFERENCES camera_view_scores(id),
    component_key TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (score_id, component_key)
);
CREATE TABLE IF NOT EXISTS run_artifacts (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY (run_id, kind)
);
"""

PIPELINE_VERSION = "1"
EVENT_GAPS = {
    "storm": timedelta(minutes=30),
    "aurora": timedelta(hours=2),
    "cloud_patch": timedelta(hours=7),
}
SOURCE_NAMES = {
    "storm": "NOAA ProbSevere v3",
    "aurora": "NOAA OVATION",
    "cloud_patch": "DWD ICON",
}


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def inserted_id(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("SQLite insert returned no row ID")
    return row_id


def utc_text(value: str) -> str:
    return parse_utc_time(value).isoformat(timespec="seconds")


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize(database_path: Path) -> None:
    with closing(connect(database_path)) as connection:
        connection.executescript(SCHEMA)
        run_columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)")}
        if "duration_seconds" not in run_columns:
            connection.execute(
                "ALTER TABLE runs ADD COLUMN duration_seconds REAL CHECK (duration_seconds >= 0)"
            )
            connection.commit()


def existing_or_new_event(
    connection: sqlite3.Connection, kind: str, source_id: str, valid_at: str
) -> int:
    source = SOURCE_NAMES[kind]
    earlier = (parse_utc_time(valid_at) - EVENT_GAPS[kind]).isoformat(
        timespec="seconds"
    )
    row = connection.execute(
        """SELECT id FROM events
           WHERE kind = ? AND source = ? AND source_id = ?
             AND last_seen_at_utc >= ? AND first_seen_at_utc <= ?
           ORDER BY last_seen_at_utc DESC LIMIT 1""",
        (kind, source, source_id, earlier, valid_at),
    ).fetchone()
    if row is not None:
        connection.execute(
            "UPDATE events SET last_seen_at_utc = MAX(last_seen_at_utc, ?) WHERE id = ?",
            (valid_at, row["id"]),
        )
        return row["id"]
    cursor = connection.execute(
        """INSERT INTO events
           (kind, source, source_id, first_seen_at_utc, last_seen_at_utc)
           VALUES (?, ?, ?, ?, ?)""",
        (kind, source, source_id, valid_at, valid_at),
    )
    return inserted_id(cursor)


def insert_event_sample(
    connection: sqlite3.Connection,
    run_id: int,
    kind: str,
    feature: dict[str, Any],
    valid_at: str,
) -> int:
    properties = feature["properties"]
    source_id = str(properties["id"])
    event_id = existing_or_new_event(connection, kind, source_id, valid_at)
    circle = properties.get("circle")
    view_circle = properties.get("view_circle")
    interestingness = (
        properties["score"]
        if kind == "cloud_patch"
        else properties["interestingness"]["score"]
    )
    cursor = connection.execute(
        """INSERT INTO event_samples
           (event_id, run_id, valid_at_utc, center_lat, center_lon,
            core_radius_km, view_radius_km, interestingness, feature_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            run_id,
            valid_at,
            circle["center_latitude"] if circle is not None else None,
            circle["center_longitude"] if circle is not None else None,
            circle["radius_km"] if circle is not None else None,
            view_circle["radius_km"] if view_circle is not None else None,
            interestingness,
            compact_json(feature),
        ),
    )
    sample_id = inserted_id(cursor)
    if kind == "storm":
        shape = properties["outline_shape"]
        connection.execute(
            """INSERT INTO storm_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sample_id,
                properties["probability"],
                properties["hail_probability"],
                properties["wind_probability"],
                properties["tornado_probability"],
                properties["flashes_5min"],
                properties["reflectivity_dbz"],
                shape["score"],
                shape["jaggedness"],
                shape["nonconvexity"],
                shape["fragmentation"],
                shape["component_count"],
            ),
        )
    elif kind == "aurora":
        connection.execute(
            "INSERT INTO aurora_metrics VALUES (?, ?, ?)",
            (sample_id, properties["aurora_percent"], properties["cloud_cover_percent"]),
        )
    else:
        connection.execute(
            "INSERT INTO cloud_patch_metrics VALUES (?, ?, ?, ?)",
            (
                sample_id,
                properties["horizontal_variation"],
                properties["vertical_variation"],
                properties["peak_cloud_fraction"],
            ),
        )
    return sample_id


def insert_score(
    connection: sqlite3.Connection,
    camera_sample_id: int,
    scorer_key: str,
    version: str,
    value: float,
    threshold: float | None = None,
    passed: bool | None = None,
    components: dict[str, float] | None = None,
) -> None:
    cursor = connection.execute(
        """INSERT INTO camera_view_scores
           (camera_sample_id, scorer_key, scorer_version, value, threshold, passed)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (camera_sample_id, scorer_key, version, value, threshold, passed),
    )
    if components:
        connection.executemany(
            """INSERT INTO camera_view_score_components
               (score_id, component_key, value) VALUES (?, ?, ?)""",
            ((inserted_id(cursor), key, component) for key, component in components.items()),
        )


def insert_camera_sample(
    connection: sqlite3.Connection,
    run_id: int,
    camera: dict[str, Any],
    event_ids: dict[tuple[str, str], int],
    model_version: str,
    blur_threshold: float,
    archived_url: str | None,
) -> None:
    frame = camera["frame"]
    camera_data = {
        key: value
        for key, value in camera.items()
        if key
        not in {
            "event_ids", "aurora_event_ids", "sunset_score", "sunset_band",
            "aurora_cloud_cover_percent", "aurora_dark", "sharpness",
            "image_scores", "view_score", "sunset_view_score", "rank", "frame",
        }
    }
    cursor = connection.execute(
        """INSERT INTO camera_samples
           (run_id, network, provider_id, camera_json, captured_at_utc,
            frame_url, archived_url)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            camera["network"],
            camera["provider_id"],
            compact_json(camera_data),
            parse_utc_time(frame["captured_at"]).isoformat(timespec="microseconds")
            if frame is not None
            else None,
            frame["image_url"] if frame is not None else None,
            archived_url,
        ),
    )
    sample_id = inserted_id(cursor)
    match_keys = [("storm", source_id) for source_id in camera["event_ids"]]
    match_keys.extend(("aurora", source_id) for source_id in camera["aurora_event_ids"])
    connection.executemany(
        "INSERT INTO camera_event_matches VALUES (?, ?)",
        ((sample_id, event_ids[key]) for key in match_keys),
    )
    insert_score(connection, sample_id, "sunset_forecast", "ICON-1", camera["sunset_score"])
    insert_score(connection, sample_id, "sunset_band", "solar-1", int(camera["sunset_band"]))
    if camera["aurora_event_ids"] and camera["aurora_cloud_cover_percent"] is not None:
        insert_score(
            connection, sample_id, "aurora_cloud_cover", "GFS-1",
            camera["aurora_cloud_cover_percent"],
        )
    if camera["aurora_event_ids"]:
        insert_score(connection, sample_id, "aurora_dark", "solar-1", int(camera["aurora_dark"]))
    if camera["sharpness"] is not None:
        insert_score(
            connection, sample_id, "sharpness", "laplacian-1",
            camera["sharpness"], blur_threshold,
            camera["sharpness"] >= blur_threshold,
        )
    if camera["image_scores"] is not None:
        insert_score(
            connection, sample_id, "warm_tone", "warm-tone-1",
            camera["image_scores"]["warm_tone_strength"],
        )
    storm = camera["view_score"]
    if storm is not None:
        insert_score(
            connection, sample_id, "storm_view", model_version,
            storm["margin"], storm["threshold"], storm["accepted"],
            {
                "good_similarity": storm["storm_similarity"],
                "bad_similarity": storm["rejected_similarity"],
                "scenic_similarity": storm["scenic_similarity"],
                "poor_similarity": storm["poor_similarity"],
            },
        )
    sunset = camera["sunset_view_score"]
    if sunset is not None:
        insert_score(
            connection, sample_id, "sunset_view", model_version,
            sunset["combined_score"], sunset["threshold"], sunset["accepted"],
            {
                "good_similarity": sunset["good_similarity"],
                "bad_similarity": sunset["bad_similarity"],
                "clip_margin": sunset["clip_margin"],
            },
        )
    rank = camera["rank"]
    if rank is not None:
        components = {
            "sharpness_percentile": rank["sharpness_score"],
            "sharpness_contribution": rank["sharpness_contribution"],
        }
        for kind, part in rank["components"].items():
            components[f"{kind}_view_percentile"] = part["view_score"]
            components[f"{kind}_event_score"] = part["event_score"]
            components[f"{kind}_contribution"] = part["weighted_score"]
        insert_score(
            connection, sample_id, "overall_rank", "rank-1", rank["score"],
            components=components,
        )


def source_rows(data: dict[str, Any], run_id: int) -> list[tuple[Any, ...]]:
    metadata = data["metadata"]
    sunset = data["sunset"]
    clouds = data["clouds"]
    rows = [
        (run_id, "probsevere", metadata["source_url"], utc_text(metadata["valid_time"]), None),
        (run_id, "icon_cloud", clouds["source_url"], None, utc_text(clouds["forecast_time"])),
    ]
    if sunset["forecast_time"] != clouds["forecast_time"]:
        raise ValueError("Sunset and cloud layers have different ICON valid times")
    if data["auroras"] is not None:
        aurora = data["auroras"]
        rows.extend(
            [
                (
                    run_id, "ovation", OVATION_URL,
                    utc_text(aurora["observation_time"]),
                    utc_text(aurora["forecast_time"]),
                ),
                (
                    run_id, "gfs_cloud", aurora["cloud_source_url"], None,
                    utc_text(aurora["cloud_time"]),
                ),
            ]
        )
    return rows


def save_run(
    database_path: Path,
    data: dict[str, Any],
    requested_at: datetime | None,
    slot_at: datetime | None,
    assets_dir: Path,
    archived_frames: dict[tuple[str, str], str],
    started_at: float,
) -> int:
    camera_keys = []
    catalog_rows = []
    for camera in data["cameras"]:
        provider_id = camera["provider_id"]
        if provider_id is None:
            raise ValueError(f"Camera lacks provider ID: {camera['network']} {camera['name']}")
        camera_keys.append((camera["network"], provider_id))
        catalog = {
            key: value
            for key, value in camera.items()
            if key in {
                "network", "provider_id", "name", "latitude", "longitude", "url",
                "operated_by", "sky_facing", "night_sky_capable", "link_only",
                "feed_verified",
            }
        }
        catalog_rows.append((camera["network"], provider_id, compact_json(catalog)))
    if len(set(camera_keys)) != len(camera_keys):
        raise ValueError("Camera provider IDs are not unique within a run")
    keys_json = compact_json(sorted(camera_keys)).encode()
    digest = hashlib.sha256(keys_json).hexdigest()
    camera_blob = zlib.compress(keys_json)
    generated_at = utc_text(data["metadata"]["generated_time"])
    map_at = utc_text(data["sunset"]["map_time"])
    model_version = data["metadata"]["visual_scorer_version"]
    blur_threshold = float(data["metadata"]["blur_threshold"])
    sunset_minimum = int(data["metadata"]["sunset_minimum_score"])
    initialize(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.execute(
            "INSERT OR IGNORE INTO camera_catalogs (digest, camera_keys) VALUES (?, ?)",
            (digest, camera_blob),
        )
        catalog_id = connection.execute(
            "SELECT id FROM camera_catalogs WHERE digest = ?", (digest,)
        ).fetchone()["id"]
        connection.executemany(
            """INSERT INTO cameras (network, provider_id, catalog_json)
               VALUES (?, ?, ?)
               ON CONFLICT(network, provider_id) DO UPDATE SET
                 catalog_json = excluded.catalog_json
               WHERE catalog_json <> excluded.catalog_json""",
            catalog_rows,
        )
        cursor = connection.execute(
            """INSERT INTO runs
               (slot_utc, requested_at_utc, generated_at_utc, map_at_utc,
                pipeline_version, catalog_id, camera_count, metadata_json,
                sunset_json, aurora_json, clouds_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                slot_at.astimezone(UTC).isoformat(timespec="minutes") if slot_at else None,
                requested_at.astimezone(UTC).isoformat(timespec="seconds") if requested_at else None,
                generated_at,
                map_at,
                PIPELINE_VERSION,
                catalog_id,
                len(camera_keys),
                compact_json(data["metadata"]),
                compact_json({
                    key: value for key, value in data["sunset"].items()
                    if key not in {"camera_in_band", "camera_scores"}
                }),
                compact_json({
                    key: value for key, value in data["auroras"].items()
                    if key not in {"features", "cameras"}
                }) if data["auroras"] is not None else None,
                compact_json({
                    key: value for key, value in data["clouds"].items()
                    if key != "features"
                }),
            ),
        )
        run_id = inserted_id(cursor)
        connection.executemany(
            """INSERT INTO run_sources
               (run_id, source, source_url, observed_at_utc, forecast_valid_at_utc)
               VALUES (?, ?, ?, ?, ?)""",
            source_rows(data, run_id),
        )
        event_ids = {}
        feature_groups = [
            ("storm", data["storms"]["features"], data["metadata"]["valid_time"]),
            ("cloud_patch", data["clouds"]["features"]["features"], data["clouds"]["forecast_time"]),
        ]
        if data["auroras"] is not None:
            feature_groups.append(
                ("aurora", data["auroras"]["features"]["features"], data["auroras"]["forecast_time"])
            )
        for kind, features, feature_time in feature_groups:
            valid_at = utc_text(feature_time)
            for feature in features:
                event_ids[(kind, str(feature["properties"]["id"]))] = insert_event_sample(
                    connection, run_id, kind, feature, valid_at
                )
        for camera in data["cameras"]:
            candidate = (
                camera["event_ids"]
                or camera["aurora_event_ids"]
                or camera["sunset_score"] >= sunset_minimum
            )
            if candidate:
                insert_camera_sample(
                    connection, run_id, camera, event_ids, model_version,
                    blur_threshold,
                    archived_frames.get((camera["network"], camera["provider_id"])),
                )
        for kind, asset_url in (
            ("sunset_band", data["sunset"]["band_url"]),
            ("sunset_quality", data["sunset"]["quality_url"]),
        ):
            asset_path = assets_dir / Path(asset_url).name
            connection.execute(
                "INSERT INTO run_artifacts VALUES (?, ?, ?, ?)",
                (
                    run_id, kind, asset_path.name,
                    hashlib.sha256(asset_path.read_bytes()).hexdigest(),
                ),
            )
        connection.execute(
            "UPDATE runs SET duration_seconds = ? WHERE id = ?",
            (perf_counter() - started_at, run_id),
        )
    return run_id
