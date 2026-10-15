import hashlib
import sqlite3
from datetime import timedelta
from typing import Any

from backend.weather_schema import CLOUD_SCORER_VERSION
from backend.weather_source import parse_utc_time
from backend.weather_storage import compact_json, inserted_id, utc_text


def cloud_result_digest(features: list[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for _, feature_json in sorted(features):
        digest.update(feature_json.encode())
    return digest.hexdigest()


def cloud_event_ids(
    connection: sqlite3.Connection, source_ids: list[str], valid_at: str
) -> dict[str, int]:
    earlier = (parse_utc_time(valid_at) - timedelta(hours=7)).isoformat(
        timespec="seconds"
    )
    existing = connection.execute(
        """SELECT id, source_id FROM events
           WHERE kind = 'cloud_patch' AND source = 'DWD ICON'
             AND first_seen_at_utc <= ? AND last_seen_at_utc >= ?
           ORDER BY last_seen_at_utc DESC""",
        (valid_at, earlier),
    )
    event_ids: dict[str, int] = {}
    for row in existing:
        event_ids.setdefault(row["source_id"], row["id"])
    missing = [source_id for source_id in source_ids if source_id not in event_ids]
    for start in range(0, len(missing), 200):
        batch = missing[start : start + 200]
        values = ",".join("('cloud_patch', 'DWD ICON', ?, ?, ?)" for _ in batch)
        rows = connection.execute(
            f"""INSERT INTO events
                (kind, source, source_id, first_seen_at_utc, last_seen_at_utc)
                VALUES {values} RETURNING id, source_id""",
            [value for source_id in batch for value in (source_id, valid_at, valid_at)],
        )
        event_ids.update((row["source_id"], row["id"]) for row in rows)
    requested_ids = [event_ids[source_id] for source_id in source_ids]
    for start in range(0, len(requested_ids), 500):
        batch = requested_ids[start : start + 500]
        placeholders = ",".join("?" for _ in batch)
        connection.execute(
            f"""UPDATE events SET last_seen_at_utc = MAX(last_seen_at_utc, ?)
                WHERE id IN ({placeholders})""",
            [valid_at, *batch],
        )
    return event_ids


def save_cloud_forecast(
    connection: sqlite3.Connection, clouds: dict[str, Any]
) -> tuple[int, dict[str, int], list[tuple[str, str]]]:
    features = clouds["features"]["features"]
    serialized = [
        (str(feature["properties"]["id"]), compact_json(feature))
        for feature in features
    ]
    valid_at = utc_text(clouds["forecast_time"])
    identity = (
        clouds["source_url"],
        valid_at,
        CLOUD_SCORER_VERSION,
        cloud_result_digest(serialized),
    )
    forecast = connection.execute(
        """SELECT id FROM cloud_forecasts WHERE source_url = ? AND valid_at_utc = ?
           AND scorer_version = ? AND result_digest = ?""",
        identity,
    ).fetchone()
    if forecast is not None:
        sample_ids = connection.execute(
            """SELECT e.source_id, s.id FROM event_samples s
               JOIN events e ON e.id = s.event_id WHERE s.cloud_forecast_id = ?""",
            (forecast["id"],),
        )
        return forecast["id"], dict(sample_ids), serialized

    forecast_id = inserted_id(
        connection.execute(
            """INSERT INTO cloud_forecasts
           (source_url, valid_at_utc, scorer_version, result_digest, sample_count)
           VALUES (?, ?, ?, ?, ?)""",
            (*identity, len(features)),
        )
    )
    event_ids = cloud_event_ids(connection, [key for key, _ in serialized], valid_at)
    sources_by_event = {
        event_id: source_id for source_id, event_id in event_ids.items()
    }
    sample_ids = {}
    for start in range(0, len(features), 200):
        batch = features[start : start + 200]
        placeholders = ",".join("(?, ?, ?, ?)" for _ in batch)
        values = [
            value
            for feature in batch
            for value in (
                event_ids[str(feature["properties"]["id"])],
                forecast_id,
                valid_at,
                feature["properties"]["score"],
            )
        ]
        rows = connection.execute(
            f"""INSERT INTO event_samples
                (event_id, cloud_forecast_id, valid_at_utc, interestingness)
                VALUES {placeholders} RETURNING id, event_id""",
            values,
        )
        sample_ids.update(
            (sources_by_event[row["event_id"]], row["id"]) for row in rows
        )
        connection.execute(
            f"INSERT INTO cloud_patch_metrics VALUES {placeholders}",
            [
                value
                for feature in batch
                for value in (
                    sample_ids[str(feature["properties"]["id"])],
                    feature["properties"]["horizontal_variation"],
                    feature["properties"]["vertical_variation"],
                    feature["properties"]["peak_cloud_fraction"],
                )
            ],
        )
    return forecast_id, sample_ids, serialized
