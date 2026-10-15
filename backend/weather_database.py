import hashlib
import sqlite3
import zlib
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.cloud_forecasts import save_cloud_forecast
from backend.phenomena.aurora.aurora import OVATION_URL
from backend.weather_migrations import migrate_forecast_storage
from backend.weather_retention import expire_history
from backend.weather_schema import SCHEMA, SCHEMA_VERSION
from backend.weather_source import parse_utc_time
from backend.weather_storage import compact_json, connect, inserted_id, utc_text

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


def initialize(database_path: Path) -> None:
    with closing(connect(database_path)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError(f"Unsupported weather database version: {version}")
        run_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(runs)")
        }
        if run_columns and "duration_seconds" not in run_columns:
            connection.execute(
                "ALTER TABLE runs ADD COLUMN duration_seconds REAL CHECK (duration_seconds >= 0)"
            )
            connection.commit()
        if run_columns and "cloud_forecast_id" not in run_columns:
            migrate_forecast_storage(connection)
        connection.executescript(SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


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
            compact_json(feature) if kind == "storm" else None,
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
            (
                sample_id,
                properties["aurora_percent"],
                properties["cloud_cover_percent"],
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
            (
                (inserted_id(cursor), key, component)
                for key, component in components.items()
            ),
        )


def insert_camera_sample(
    connection: sqlite3.Connection,
    run_id: int,
    camera: dict[str, Any],
    event_ids: dict[tuple[str, str], int],
    model_version: str,
    blur_threshold: float,
) -> None:
    frame = camera["frame"]
    camera_data = {
        key: value
        for key, value in camera.items()
        if key
        not in {
            "event_ids",
            "aurora_event_ids",
            "sunset_score",
            "sunset_band",
            "aurora_cloud_cover_percent",
            "aurora_dark",
            "sharpness",
            "image_scores",
            "view_score",
            "sunset_view_score",
            "rank",
            "frame",
        }
    }
    cursor = connection.execute(
        """INSERT INTO camera_samples
           (run_id, network, provider_id, camera_json, captured_at_utc,
            frame_url)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            camera["network"],
            camera["provider_id"],
            compact_json(camera_data),
            parse_utc_time(frame["captured_at"]).isoformat(timespec="microseconds")
            if frame is not None
            else None,
            frame["image_url"] if frame is not None else None,
        ),
    )
    sample_id = inserted_id(cursor)
    match_keys = [("storm", source_id) for source_id in camera["event_ids"]]
    match_keys.extend(("aurora", source_id) for source_id in camera["aurora_event_ids"])
    connection.executemany(
        "INSERT INTO camera_event_matches VALUES (?, ?)",
        ((sample_id, event_ids[key]) for key in match_keys),
    )
    insert_score(
        connection, sample_id, "sunset_forecast", "ICON-1", camera["sunset_score"]
    )
    insert_score(
        connection, sample_id, "sunset_band", "solar-1", int(camera["sunset_band"])
    )
    if camera["aurora_event_ids"] and camera["aurora_cloud_cover_percent"] is not None:
        insert_score(
            connection,
            sample_id,
            "aurora_cloud_cover",
            "GFS-1",
            camera["aurora_cloud_cover_percent"],
        )
    if camera["aurora_event_ids"]:
        insert_score(
            connection, sample_id, "aurora_dark", "solar-1", int(camera["aurora_dark"])
        )
    if camera["sharpness"] is not None:
        insert_score(
            connection,
            sample_id,
            "sharpness",
            "laplacian-1",
            camera["sharpness"],
            blur_threshold,
            camera["sharpness"] >= blur_threshold,
        )
    if camera["image_scores"] is not None:
        insert_score(
            connection,
            sample_id,
            "warm_tone",
            "warm-tone-1",
            camera["image_scores"]["warm_tone_strength"],
        )
    storm = camera["view_score"]
    if storm is not None:
        insert_score(
            connection,
            sample_id,
            "storm_view",
            model_version,
            storm["margin"],
            storm["threshold"],
            storm["accepted"],
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
            connection,
            sample_id,
            "sunset_view",
            model_version,
            sunset["combined_score"],
            sunset["threshold"],
            sunset["accepted"],
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
            connection,
            sample_id,
            "overall_rank",
            "rank-1",
            rank["score"],
            components=components,
        )


def source_rows(data: dict[str, Any], run_id: int) -> list[tuple[Any, ...]]:
    metadata = data["metadata"]
    sunset = data["sunset"]
    clouds = data["clouds"]
    rows = [
        (
            run_id,
            "probsevere",
            metadata["source_url"],
            utc_text(metadata["valid_time"]),
            None,
        ),
        (
            run_id,
            "icon_cloud",
            clouds["source_url"],
            None,
            utc_text(clouds["forecast_time"]),
        ),
    ]
    if sunset["forecast_time"] != clouds["forecast_time"]:
        raise ValueError("Sunset and cloud layers have different ICON valid times")
    if data["auroras"] is not None:
        aurora = data["auroras"]
        rows.extend(
            [
                (
                    run_id,
                    "ovation",
                    OVATION_URL,
                    utc_text(aurora["observation_time"]),
                    utc_text(aurora["forecast_time"]),
                ),
                (
                    run_id,
                    "gfs_cloud",
                    aurora["cloud_source_url"],
                    None,
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
    started_at: float,
) -> int:
    camera_keys = []
    catalog_rows = []
    for camera in data["cameras"]:
        provider_id = camera["provider_id"]
        if provider_id is None:
            raise ValueError(
                f"Camera lacks provider ID: {camera['network']} {camera['name']}"
            )
        camera_keys.append((camera["network"], provider_id))
        catalog = {
            key: value
            for key, value in camera.items()
            if key
            in {
                "network",
                "provider_id",
                "name",
                "latitude",
                "longitude",
                "url",
                "operated_by",
                "sky_facing",
                "night_sky_capable",
                "link_only",
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
        cloud_forecast_id, cloud_sample_ids, cloud_features = save_cloud_forecast(
            connection, data["clouds"]
        )
        event_count = len(data["storms"]["features"]) + len(cloud_features)
        if data["auroras"] is not None:
            event_count += len(data["auroras"]["features"]["features"])
        cursor = connection.execute(
            """INSERT INTO runs
               (slot_utc, requested_at_utc, generated_at_utc, map_at_utc,
                pipeline_version, catalog_id, camera_count, event_count,
                cloud_forecast_id, metadata_json,
                sunset_json, aurora_json, clouds_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                slot_at.astimezone(UTC).isoformat(timespec="minutes")
                if slot_at
                else None,
                requested_at.astimezone(UTC).isoformat(timespec="seconds")
                if requested_at
                else None,
                generated_at,
                map_at,
                PIPELINE_VERSION,
                catalog_id,
                len(camera_keys),
                event_count,
                cloud_forecast_id,
                compact_json(data["metadata"]),
                compact_json(
                    {
                        key: value
                        for key, value in data["sunset"].items()
                        if key not in {"camera_in_band", "camera_scores"}
                    }
                ),
                compact_json(
                    {
                        key: value
                        for key, value in data["auroras"].items()
                        if key not in {"features", "cameras"}
                    }
                )
                if data["auroras"] is not None
                else None,
                compact_json(
                    {
                        key: value
                        for key, value in data["clouds"].items()
                        if key != "features"
                    }
                ),
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
        ]
        if data["auroras"] is not None:
            feature_groups.append(
                (
                    "aurora",
                    data["auroras"]["features"]["features"],
                    data["auroras"]["forecast_time"],
                )
            )
        for kind, features, feature_time in feature_groups:
            valid_at = utc_text(feature_time)
            for feature in features:
                event_ids[(kind, str(feature["properties"]["id"]))] = (
                    insert_event_sample(connection, run_id, kind, feature, valid_at)
                )
        connection.execute("DELETE FROM latest_forecast_features")
        cached_features = [
            (cloud_sample_ids[source_id], run_id, feature_json)
            for source_id, feature_json in cloud_features
        ]
        if data["auroras"] is not None:
            cached_features.extend(
                (
                    event_ids[("aurora", str(feature["properties"]["id"]))],
                    run_id,
                    compact_json(feature),
                )
                for feature in data["auroras"]["features"]["features"]
            )
        connection.executemany(
            "INSERT INTO latest_forecast_features VALUES (?, ?, ?)", cached_features
        )
        for camera in data["cameras"]:
            candidate = (
                camera["event_ids"]
                or camera["aurora_event_ids"]
                or camera["sunset_score"] >= sunset_minimum
            )
            if candidate:
                insert_camera_sample(
                    connection,
                    run_id,
                    camera,
                    event_ids,
                    model_version,
                    blur_threshold,
                )
        for kind, asset_url in (
            ("sunset_band", data["sunset"]["band_url"]),
            ("sunset_quality", data["sunset"]["quality_url"]),
        ):
            asset_path = assets_dir / Path(asset_url).name
            connection.execute(
                "INSERT INTO run_artifacts VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    kind,
                    asset_path.name,
                    hashlib.sha256(asset_path.read_bytes()).hexdigest(),
                ),
            )
        expired_assets = expire_history(
            connection, assets_dir, parse_utc_time(generated_at)
        )
        connection.execute(
            "UPDATE runs SET duration_seconds = ? WHERE id = ?",
            (perf_counter() - started_at, run_id),
        )
    for path in expired_assets:
        path.unlink()
    return run_id
