import sqlite3

from backend.cloud_forecasts import cloud_result_digest
from backend.weather_schema import (
    CLOUD_FORECAST_SCHEMA,
    CLOUD_SCORER_VERSION,
    EVENT_SAMPLES_SCHEMA,
    SCHEMA,
    SCHEMA_VERSION,
)
from backend.weather_storage import inserted_id


def migrate_forecast_storage(connection: sqlite3.Connection) -> None:
    if (
        connection.execute(
            """SELECT 1 FROM camera_event_matches m
           JOIN event_samples s ON s.id = m.event_sample_id
           JOIN events e ON e.id = s.event_id WHERE e.kind = 'cloud_patch' LIMIT 1"""
        ).fetchone()
        is not None
    ):
        raise ValueError("Cloud camera matches require an explicit migration")

    connection.execute("PRAGMA foreign_keys = OFF")
    new_samples = EVENT_SAMPLES_SCHEMA.replace(
        "event_samples (", "event_samples_new (", 1
    )
    connection.executescript("BEGIN IMMEDIATE;\n" + CLOUD_FORECAST_SCHEMA + new_samples)
    connection.execute(
        "ALTER TABLE runs ADD COLUMN event_count INTEGER NOT NULL DEFAULT 0"
    )
    connection.execute(
        "ALTER TABLE runs ADD COLUMN cloud_forecast_id INTEGER REFERENCES cloud_forecasts(id)"
    )
    connection.execute(
        """UPDATE runs SET event_count = (
               SELECT COUNT(*) FROM event_samples WHERE run_id = runs.id
           )"""
    )
    connection.execute(
        """CREATE TABLE latest_forecast_features (
               sample_id INTEGER PRIMARY KEY REFERENCES event_samples(id),
               run_id INTEGER NOT NULL REFERENCES runs(id),
               feature_json TEXT NOT NULL
           )"""
    )
    latest_id = connection.execute("SELECT MAX(id) FROM runs").fetchone()[0]
    connection.execute(
        """INSERT INTO event_samples_new
           (id, event_id, run_id, valid_at_utc, center_lat, center_lon,
            core_radius_km, view_radius_km, interestingness, feature_json)
           SELECT s.id, s.event_id, s.run_id, s.valid_at_utc, s.center_lat, s.center_lon,
                  s.core_radius_km, s.view_radius_km, s.interestingness,
                  CASE WHEN e.kind = 'storm' THEN s.feature_json END
           FROM event_samples s JOIN events e ON e.id = s.event_id
           WHERE e.kind <> 'cloud_patch'"""
    )
    connection.execute(
        """INSERT INTO latest_forecast_features
           SELECT s.id, s.run_id, s.feature_json FROM event_samples s
           JOIN events e ON e.id = s.event_id
           WHERE s.run_id = ? AND e.kind = 'aurora'""",
        (latest_id,),
    )
    forecasts = {}
    runs = connection.execute(
        """SELECT r.id, s.source_url, s.forecast_valid_at_utc
           FROM runs r JOIN run_sources s ON s.run_id = r.id
           WHERE s.source = 'icon_cloud' ORDER BY r.id"""
    ).fetchall()
    for run in runs:
        features = connection.execute(
            """SELECT e.source_id, s.feature_json FROM event_samples s
               JOIN events e ON e.id = s.event_id
               WHERE s.run_id = ? AND e.kind = 'cloud_patch'""",
            (run["id"],),
        ).fetchall()
        identity = (
            run["source_url"],
            run["forecast_valid_at_utc"],
            CLOUD_SCORER_VERSION,
            cloud_result_digest([(row[0], row[1]) for row in features]),
        )
        if identity not in forecasts:
            forecast_id = inserted_id(
                connection.execute(
                    """INSERT INTO cloud_forecasts
                   (source_url, valid_at_utc, scorer_version, result_digest, sample_count)
                   VALUES (?, ?, ?, ?, ?)""",
                    (*identity, len(features)),
                )
            )
            forecasts[identity] = forecast_id
            connection.execute(
                """INSERT INTO event_samples_new
                   (id, event_id, cloud_forecast_id, valid_at_utc, interestingness)
                   SELECT s.id, s.event_id, ?, s.valid_at_utc, s.interestingness
                   FROM event_samples s JOIN events e ON e.id = s.event_id
                   WHERE s.run_id = ? AND e.kind = 'cloud_patch'""",
                (forecast_id, run["id"]),
            )
        forecast_id = forecasts[identity]
        connection.execute(
            "UPDATE runs SET cloud_forecast_id = ? WHERE id = ?",
            (forecast_id, run["id"]),
        )
        if run["id"] != latest_id:
            continue
        connection.execute(
            """INSERT INTO latest_forecast_features
               SELECT canonical.id, ?, original.feature_json
               FROM event_samples original JOIN events e ON e.id = original.event_id
               JOIN events canonical_event ON canonical_event.source_id = e.source_id
                 AND canonical_event.kind = 'cloud_patch' AND canonical_event.source = 'DWD ICON'
               JOIN event_samples_new canonical ON canonical.event_id = canonical_event.id
                 AND canonical.cloud_forecast_id = ?
               WHERE original.run_id = ? AND e.kind = 'cloud_patch'""",
            (latest_id, forecast_id, latest_id),
        )
    connection.execute(
        "DELETE FROM cloud_patch_metrics WHERE sample_id NOT IN (SELECT id FROM event_samples_new)"
    )
    connection.execute("DROP TABLE event_samples")
    connection.execute("ALTER TABLE event_samples_new RENAME TO event_samples")
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("Forecast migration left invalid foreign keys")
