import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

HISTORY_RETENTION = timedelta(days=10)


def expire_history(
    connection: sqlite3.Connection, assets_dir: Path, at: datetime
) -> list[Path]:
    cutoff = (at - HISTORY_RETENTION).isoformat(timespec="seconds")
    connection.execute("CREATE TEMP TABLE expired_runs (id INTEGER PRIMARY KEY)")
    connection.execute(
        "INSERT INTO expired_runs SELECT id FROM runs WHERE generated_at_utc < ?",
        (cutoff,),
    )
    if connection.execute("SELECT 1 FROM expired_runs LIMIT 1").fetchone() is None:
        connection.execute("DROP TABLE expired_runs")
        return []
    overlays = connection.execute(
        """SELECT DISTINCT old.relative_path FROM run_artifacts old
           WHERE old.run_id IN expired_runs AND NOT EXISTS (
               SELECT 1 FROM run_artifacts retained
               WHERE retained.relative_path = old.relative_path
                 AND retained.run_id NOT IN expired_runs
           )"""
    ).fetchall()
    frames = connection.execute(
        """SELECT DISTINCT old.archived_url FROM camera_samples old
           WHERE old.run_id IN expired_runs AND old.archived_url IS NOT NULL
             AND NOT EXISTS (
               SELECT 1 FROM camera_samples retained
               WHERE retained.archived_url = old.archived_url
                 AND retained.run_id NOT IN expired_runs
           )"""
    ).fetchall()
    connection.execute(
        """DELETE FROM camera_view_score_components WHERE score_id IN (
               SELECT s.id FROM camera_view_scores s JOIN camera_samples c
               ON c.id = s.camera_sample_id WHERE c.run_id IN expired_runs
           )"""
    )
    connection.execute(
        """DELETE FROM camera_view_scores WHERE camera_sample_id IN (
               SELECT id FROM camera_samples WHERE run_id IN expired_runs
           )"""
    )
    connection.execute(
        """DELETE FROM camera_event_matches WHERE camera_sample_id IN (
               SELECT id FROM camera_samples WHERE run_id IN expired_runs
           )"""
    )
    connection.execute("DELETE FROM camera_samples WHERE run_id IN expired_runs")
    connection.execute(
        "DELETE FROM latest_forecast_features WHERE run_id IN expired_runs"
    )
    connection.execute(
        "CREATE TEMP TABLE expired_samples (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL)"
    )
    connection.execute(
        """INSERT INTO expired_samples SELECT id, event_id FROM event_samples
           WHERE run_id IN expired_runs OR cloud_forecast_id IN (
               SELECT id FROM cloud_forecasts WHERE id NOT IN (
                   SELECT cloud_forecast_id FROM runs
                   WHERE id NOT IN expired_runs AND cloud_forecast_id IS NOT NULL
               )
           )"""
    )
    for table in ("cloud_patch_metrics", "storm_metrics", "aurora_metrics"):
        connection.execute(
            f"DELETE FROM {table} WHERE sample_id IN (SELECT id FROM expired_samples)"
        )
    connection.execute(
        "DELETE FROM event_samples WHERE id IN (SELECT id FROM expired_samples)"
    )
    connection.execute("DELETE FROM run_artifacts WHERE run_id IN expired_runs")
    connection.execute("DELETE FROM run_sources WHERE run_id IN expired_runs")
    connection.execute("DELETE FROM runs WHERE id IN expired_runs")
    connection.execute(
        """DELETE FROM cloud_forecasts WHERE id NOT IN (
               SELECT cloud_forecast_id FROM runs WHERE cloud_forecast_id IS NOT NULL
           )"""
    )
    connection.execute(
        """DELETE FROM events WHERE id IN (SELECT event_id FROM expired_samples)
           AND NOT EXISTS (SELECT 1 FROM event_samples s WHERE s.event_id = events.id)"""
    )
    connection.execute(
        "DELETE FROM camera_catalogs WHERE id NOT IN (SELECT catalog_id FROM runs)"
    )
    connection.execute("DROP TABLE expired_samples")
    connection.execute("DROP TABLE expired_runs")
    return [assets_dir / row[0] for row in overlays] + [
        assets_dir / row[0].removeprefix("/assets/") for row in frames
    ]
