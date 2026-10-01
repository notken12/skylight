import argparse
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.weather_source import fetch_bytes, fetch_faa_json

FAA_REFERER = "https://weathercams.faa.gov/"


def fetch_latest_image(
    camera_id: int, at: datetime, fetch_json: Callable[[str], Any]
) -> dict[str, Any]:
    url = f"https://weathercams.faa.gov/api/cameras/{camera_id}/images/last/24"
    images = fetch_json(url)["payload"]
    return max(
        (
            image
            for image in images
            if datetime.fromisoformat(image["imageDatetime"]) <= at
        ),
        key=lambda image: image["imageDatetime"],
    )


def collect_snapshot(
    sample: dict[str, Any], at: datetime, output_dir: Path
) -> dict[str, Any]:
    image = fetch_latest_image(sample["camera_id"], at, fetch_faa_json)
    jpeg = fetch_bytes(image["imageUri"], referer=FAA_REFERER)
    filename = image["imageFilename"]
    (output_dir / filename).write_bytes(jpeg)
    return {
        **sample,
        "filename": filename,
        "captured_at": image["imageDatetime"],
        "image_url": image["imageUri"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save FAA camera snapshots with provenance."
    )
    parser.add_argument("input", type=Path, help="JSON list of camera sample records")
    parser.add_argument("--at", help="Latest frame at or before this ISO 8601 UTC time")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    at = datetime.fromisoformat(arguments.at) if arguments.at else datetime.now(UTC)
    samples = json.loads(arguments.input.read_text())
    arguments.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(
            executor.map(
                lambda sample: collect_snapshot(sample, at, arguments.output), samples
            )
        )
    (arguments.output / "manifest.json").write_text(
        json.dumps(
            {"selected_at": at.isoformat(), "samples": records},
            indent=2,
        )
        + "\n"
    )
    print(f"Saved {len(records)} snapshots to {arguments.output}")


if __name__ == "__main__":
    main()
