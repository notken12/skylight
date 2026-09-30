import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import numpy as np
from numpy.typing import NDArray

from phenomena.storm.scene_data import (
    CloudGrid,
    RadarGrid,
    goes_cloud_mask,
    goes_source,
    mrms_mask,
    mrms_source,
    read_goes_grid,
    read_mrms_grid,
)
from phenomena.storm.shape_complexity import ShapeComplexity, score_mask
from weather_source import fetch_bytes, fetch_text, parse_utc_time

type FetchText = Callable[[str], str]
type FetchBytes = Callable[[str], bytes]


def load_radar_grid(
    at: datetime | None, read_text: FetchText, read_bytes: FetchBytes
) -> RadarGrid:
    url = mrms_source(at, read_text)
    return read_mrms_grid(read_bytes(url), url)


def load_cloud_grid(
    at: datetime, longitude: float, read_text: FetchText, read_bytes: FetchBytes
) -> CloudGrid:
    url = goes_source(at, longitude, read_text)
    return read_goes_grid(read_bytes(url), url)


def require_fresh(valid_time: datetime, target_time: datetime, source: str) -> None:
    age = target_time - valid_time
    if not timedelta(0) <= age <= timedelta(minutes=15):
        raise ValueError(f"{source} observation is {age} from requested time")


def describe_mask(name: str, mask: NDArray[np.bool_], shape: ShapeComplexity) -> None:
    coverage = 100 * np.count_nonzero(mask) / mask.size
    print(
        f"{name}: {shape.score:.1f}/100 complexity; "
        f"jagged {shape.jaggedness:.3f}, nonconvex {shape.nonconvexity:.3f}, "
        f"fragmented {shape.fragmentation:.3f}; "
        f"{shape.component_count} pieces; {coverage:.1f}% of window covered"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score the shape complexity of local MRMS rain and GOES cloud areas."
    )
    parser.add_argument("latitude", type=float)
    parser.add_argument("longitude", type=float)
    parser.add_argument(
        "--radius-km", type=float, default=100, help="Half-width of the local window."
    )
    parser.add_argument(
        "--reflectivity-dbz",
        type=float,
        default=20,
        help="Minimum MRMS low-level reflectivity included in the rain-area mask.",
    )
    parser.add_argument(
        "--min-component-pixels",
        type=int,
        default=4,
        help="Ignore connected pieces smaller than this many pixels.",
    )
    parser.add_argument("--at", help="UTC ISO 8601 time; default latest.")
    arguments = parser.parse_args()
    target = parse_utc_time(arguments.at) if arguments.at else datetime.now(UTC)

    with ThreadPoolExecutor(max_workers=2) as executor:
        radar_future = executor.submit(
            load_radar_grid, target if arguments.at else None, fetch_text, fetch_bytes
        )
        cloud_future = executor.submit(
            load_cloud_grid, target, arguments.longitude, fetch_text, fetch_bytes
        )
        radar = radar_future.result()
        cloud = cloud_future.result()

    require_fresh(radar.valid_time, target, "MRMS")
    require_fresh(cloud.valid_time, target, "GOES")
    rain_mask = mrms_mask(
        radar,
        arguments.latitude,
        arguments.longitude,
        arguments.radius_km,
        arguments.reflectivity_dbz,
    )
    cloud_mask = goes_cloud_mask(
        cloud, arguments.latitude, arguments.longitude, arguments.radius_km
    )
    rain_shape = score_mask(rain_mask, arguments.min_component_pixels)
    cloud_shape = score_mask(cloud_mask, arguments.min_component_pixels)

    print(
        f"Window: {arguments.latitude:.4f}, {arguments.longitude:.4f}; "
        f"±{arguments.radius_km:g} km in latitude and longitude"
    )
    print(f"MRMS: {radar.valid_time.isoformat()} · {radar.source_url}")
    print(f"GOES: {cloud.valid_time.isoformat()} · {cloud.source_url}")
    describe_mask(
        f"Rain area ≥{arguments.reflectivity_dbz:g} dBZ", rain_mask, rain_shape
    )
    describe_mask("Cloud area", cloud_mask, cloud_shape)


if __name__ == "__main__":
    main()
