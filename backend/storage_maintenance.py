import argparse
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from backend.weather_database import initialize
from backend.weather_retention import expire_history
from backend.weather_storage import connect


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate and expire saved weather history."
    )
    parser.add_argument(
        "--database", type=Path, default=Path("output/skylight.sqlite3")
    )
    parser.add_argument("--assets-dir", type=Path, default=Path("output/assets"))
    parser.add_argument("--compact-to", type=Path)
    arguments = parser.parse_args()
    original_bytes = arguments.database.stat().st_size
    initialize(arguments.database)
    with closing(connect(arguments.database)) as connection:
        with connection:
            expired_assets = expire_history(
                connection, arguments.assets_dir, datetime.now(UTC)
            )
        for path in expired_assets:
            path.unlink()
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Weather database has invalid foreign keys")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Weather database failed its integrity check")
        if arguments.compact_to is not None:
            connection.execute("VACUUM INTO ?", (str(arguments.compact_to),))
        print(
            json.dumps(
                {
                    "original_bytes": original_bytes,
                    "compacted_bytes": arguments.compact_to.stat().st_size
                    if arguments.compact_to
                    else None,
                    "runs": connection.execute("SELECT COUNT(*) FROM runs").fetchone()[
                        0
                    ],
                    "cloud_forecasts": connection.execute(
                        "SELECT COUNT(*) FROM cloud_forecasts"
                    ).fetchone()[0],
                    "expired_assets": len(expired_assets),
                }
            )
        )


if __name__ == "__main__":
    main()
