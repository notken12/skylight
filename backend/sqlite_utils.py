import sqlite3


def inserted_id(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("SQLite insert returned no row ID")
    return row_id
