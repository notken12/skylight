import json
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path
from typing import Any

from weather_database import connect, initialize


def run_for_slot(database_path: Path, slot_at: str) -> int | None:
    initialize(database_path)
    with closing(connect(database_path)) as connection:
        row = connection.execute(
            "SELECT id FROM runs WHERE slot_utc = ?", (slot_at,)
        ).fetchone()
    return row["id"] if row is not None else None


def list_runs(
    database_path: Path, limit: int, before: int | None = None
) -> list[dict[str, Any]]:
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            """SELECT r.id, r.generated_at_utc, r.map_at_utc, r.camera_count,
                      s.observed_at_utc AS storm_valid_at_utc,
                      (SELECT COUNT(*) FROM event_samples es WHERE es.run_id = r.id)
                      AS event_count
               FROM runs r
               JOIN run_sources s ON s.run_id = r.id AND s.source = 'probsevere'
               WHERE (? IS NULL OR r.id < ?)
               ORDER BY r.id DESC LIMIT ?""",
            (before, before, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def event_history(database_path: Path, event_id: int) -> dict[str, Any] | None:
    with closing(connect(database_path)) as connection:
        event = connection.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            return None
        samples = connection.execute(
            """SELECT es.id, es.run_id, es.valid_at_utc, es.interestingness,
                      es.center_lat, es.center_lon, es.core_radius_km,
                      es.view_radius_km, es.feature_json
               FROM event_samples es WHERE es.event_id = ?
               ORDER BY es.valid_at_utc""",
            (event_id,),
        ).fetchall()
    return {
        "event": dict(event),
        "samples": [
            {key: value for key, value in dict(sample).items() if key != "feature_json"}
            | {"feature": json.loads(sample["feature_json"])}
            for sample in samples
        ],
    }


def camera_history(
    database_path: Path, network: str, provider_id: str, limit: int
) -> list[dict[str, Any]]:
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            """SELECT cs.id, cs.run_id, cs.captured_at_utc, cs.frame_url,
                      cs.archived_url, r.generated_at_utc
               FROM camera_samples cs
               JOIN runs r ON r.id = cs.run_id
               WHERE cs.network = ? AND cs.provider_id = ?
               ORDER BY cs.run_id DESC LIMIT ?""",
            (network, provider_id, limit),
        ).fetchall()
        score_rows = connection.execute(
            """SELECT s.camera_sample_id, s.scorer_key, s.value, s.threshold, s.passed
               FROM camera_view_scores s
               WHERE (s.scorer_key <> 'aurora_cloud_cover' OR EXISTS (
                   SELECT 1 FROM camera_event_matches m
                   JOIN event_samples es ON es.id = m.event_sample_id
                   JOIN events e ON e.id = es.event_id
                   WHERE m.camera_sample_id = s.camera_sample_id AND e.kind = 'aurora'
               ))
               AND s.camera_sample_id IN (
                   SELECT id FROM camera_samples
                   WHERE network = ? AND provider_id = ?
                   ORDER BY run_id DESC LIMIT ?
               )""",
            (network, provider_id, limit),
        ).fetchall()
        scores_by_sample: dict[int, list[dict[str, Any]]] = {}
        for score in score_rows:
            scores_by_sample.setdefault(score["camera_sample_id"], []).append(dict(score))
        result = [
            dict(row) | {"scores": scores_by_sample.get(row["id"], [])}
            for row in rows
        ]
    return result


def catalog_cameras(
    connection: sqlite3.Connection, keys: list[list[str]]
) -> dict[tuple[str, str], dict[str, Any]]:
    cameras = {}
    if not keys:
        return cameras
    for start in range(0, len(keys), 400):
        batch = keys[start : start + 400]
        placeholders = ",".join("(?, ?)" for _ in batch)
        rows = connection.execute(
            f"""SELECT network, provider_id, catalog_json FROM cameras
                WHERE (network, provider_id) IN ({placeholders})""",
            [part for key in batch for part in key],
        ).fetchall()
        for row in rows:
            cameras[(row["network"], row["provider_id"])] = json.loads(
                row["catalog_json"]
            )
    if len(cameras) != len(keys):
        raise ValueError("Run camera catalog is incomplete")
    return cameras


def read_run_map(database_path: Path, run_id: int) -> dict[str, Any] | None:
    with closing(connect(database_path)) as connection:
        run = connection.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run is None:
            return None
        catalog_row = connection.execute(
            "SELECT camera_keys FROM camera_catalogs WHERE id = ?",
            (run["catalog_id"],),
        ).fetchone()
        keys = json.loads(zlib.decompress(catalog_row["camera_keys"]))
        catalog = catalog_cameras(connection, keys)
        event_rows = connection.execute(
            """SELECT es.id, es.event_id, es.valid_at_utc,
                      e.kind, e.source_id, es.feature_json
               FROM event_samples es JOIN events e ON e.id = es.event_id
               WHERE es.run_id = ? ORDER BY es.id""",
            (run_id,),
        ).fetchall()
        events = [
            {
                "id": row["id"],
                "event_id": row["event_id"],
                "kind": row["kind"],
                "source_id": row["source_id"],
                "valid_at_utc": row["valid_at_utc"],
                "feature": json.loads(row["feature_json"]),
            }
            for row in event_rows
        ]
        sample_rows = connection.execute(
            "SELECT * FROM camera_samples WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        samples: dict[int, dict[str, Any]] = {}
        for row in sample_rows:
            samples[row["id"]] = {
                "id": row["id"],
                "run_id": row["run_id"],
                "camera": json.loads(row["camera_json"]),
                "captured_at_utc": row["captured_at_utc"],
                "frame_url": row["frame_url"],
                "archived_url": row["archived_url"],
                "event_sample_ids": [],
                "scores": {},
            }
        matches: dict[int, list[int]] = {}
        for row in connection.execute(
            """SELECT s.id, s.camera_sample_id, s.scorer_key, s.scorer_version,
                      s.value, s.threshold, s.passed
               FROM camera_view_scores s
               JOIN camera_samples cs ON cs.id = s.camera_sample_id
               WHERE cs.run_id = ?""",
            (run_id,),
        ):
            samples[row["camera_sample_id"]]["scores"][row["scorer_key"]] = {
                "value": row["value"],
                "threshold": row["threshold"],
                "passed": None if row["passed"] is None else bool(row["passed"]),
                "version": row["scorer_version"],
                "components": {},
            }
        for row in connection.execute(
            """SELECT s.camera_sample_id, s.scorer_key, c.component_key, c.value
               FROM camera_view_score_components c
               JOIN camera_view_scores s ON s.id = c.score_id
               JOIN camera_samples cs ON cs.id = s.camera_sample_id
               WHERE cs.run_id = ?""",
            (run_id,),
        ):
            samples[row["camera_sample_id"]]["scores"][row["scorer_key"]][
                "components"
            ][row["component_key"]] = row["value"]
        for row in connection.execute(
            """SELECT m.camera_sample_id, m.event_sample_id
               FROM camera_event_matches m
               JOIN camera_samples cs ON cs.id = m.camera_sample_id
               WHERE cs.run_id = ?""",
            (run_id,),
        ):
            matches.setdefault(row["camera_sample_id"], []).append(row["event_sample_id"])
        for sample_id, event_ids in matches.items():
            samples[sample_id]["event_sample_ids"] = event_ids
        camera_samples = {
            (row["network"], row["provider_id"]): samples[row["id"]]
            for row in sample_rows
        }
        cameras = [
            {
                "catalog": catalog[(network, provider_id)],
                "sample": camera_samples.get((network, provider_id)),
            }
            for network, provider_id in keys
        ]
        sources = [
            dict(row)
            for row in connection.execute(
                "SELECT source, source_url, observed_at_utc, forecast_valid_at_utc FROM run_sources WHERE run_id = ?",
                (run_id,),
            )
        ]
    return {
        "run": {
            "id": run["id"],
            "generated_at_utc": run["generated_at_utc"],
            "map_at_utc": run["map_at_utc"],
            "camera_count": run["camera_count"],
            "metadata": json.loads(run["metadata_json"]),
            "sunset": json.loads(run["sunset_json"]),
            "aurora": json.loads(run["aurora_json"]) if run["aurora_json"] else None,
            "clouds": json.loads(run["clouds_json"]),
        },
        "sources": sources,
        "events": events,
        "cameras": cameras,
    }
