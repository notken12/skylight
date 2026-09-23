import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from camera_matching import match_cameras
from cameras import load_cameras
from event_geometry import enclosing_circle
from map_render import render_map
from probsevere import classify_storms
from shape_complexity import score_shape
from weather_source import (
    fetch_faa_json,
    fetch_json,
    fetch_text,
    parse_utc_time,
    probsevere_source,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render ProbSevere storm polygons and public camera links on a US map."
    )
    parser.add_argument(
        "--at",
        help="Select the latest storm snapshot at or before this ISO 8601 time (UTC).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/storm_map.html"),
        help="HTML output path (default: output/storm_map.html).",
    )
    arguments = parser.parse_args()
    requested_time = parse_utc_time(arguments.at) if arguments.at else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        camera_future = executor.submit(load_cameras, fetch_json, fetch_faa_json)
        source_url = probsevere_source(requested_time, fetch_text)
        weather_data = fetch_json(source_url)
        cameras = camera_future.result()

    storms = classify_storms(weather_data, score_shape, enclosing_circle)
    matched_cameras = match_cameras(storms, cameras)
    metadata = {
        "valid_time": weather_data["validTime"],
        "generated_time": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_url": source_url,
    }
    render_map(storms, matched_cameras, metadata, arguments.output)
    print(
        f"Wrote {arguments.output}: {len(storms['features'])} storms, {len(cameras)} cameras, "
        f"{sum(bool(camera.event_ids) for camera in matched_cameras)} candidate views"
    )


if __name__ == "__main__":
    main()
