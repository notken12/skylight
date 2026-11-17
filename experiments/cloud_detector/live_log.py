import csv
import json
from pathlib import Path
from typing import Any

LIVE_DIR = Path("output/cloud_live")
RARE_VISION_TYPES = frozenset(
    {
        "mammatus",
        "lenticular",
        "asperitas",
        "kelvin_helmholtz",
        "shelf_cloud",
        "roll_cloud",
        "noctilucent",
    }
)


def read_label(run_dir: Path, frame_name: str) -> dict[str, str]:
    return json.loads(
        (run_dir / "labels" / Path(frame_name).with_suffix(".json")).read_text()
    )


def worth_reviewing(vision_type: str, vision_confidence: str) -> bool:
    return vision_type in RARE_VISION_TYPES or vision_confidence == "low"


def logged_columns(log: Path) -> list[str]:
    with log.open(newline="") as file:
        return next(csv.reader(file))


def upgrade_log_columns(log: Path, columns: list[str]) -> None:
    with log.open(newline="") as file:
        logged_rows = list(csv.DictReader(file))
    upgraded = log.with_suffix(".upgrading.csv")
    with upgraded.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(logged_rows)
    upgraded.replace(log)


def append_to_log(log: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(rows[0])
    if log.exists() and logged_columns(log) != columns:
        upgrade_log_columns(log, columns)
    is_new_log = not log.exists()
    with log.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        if is_new_log:
            writer.writeheader()
        writer.writerows(rows)
