import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.weather_source import parse_utc_time


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
