import bz2
import tarfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from eccodes import codes_get, codes_get_values, codes_grib_new_from_file, codes_release
from netCDF4 import Dataset
from numpy.typing import NDArray

from cloud_volume import CloudVolume
from weather_source import fetch_bytes

ICON_MODEL_LEVELS = (*range(56, 91), *range(92, 121, 2))
ICON_HALF_LEVELS = tuple(range(55, 121))
ICON_BASE_URL = "https://opendata.dwd.de/weather/nwp/icon/grib"
ICON_WEIGHTS_URL = (
    "https://opendata.dwd.de/weather/lib/cdo/ICON_GLOBAL2WORLD_025_EASY.tar.bz2"
)
ICON_WEIGHTS_MEMBER = "ICON_GLOBAL2WORLD_025_EASY/weights_icogl2world_025.nc"
ICON_CACHE_DIR = Path(__file__).parent / "output/icon_cache"
SOUTH, NORTH, WEST, EAST = 17, 85, 170, 310
GRID_STEP = 0.25
GRID_SHAPE = (int((NORTH - SOUTH) / GRID_STEP) + 1, int((EAST - WEST) / GRID_STEP) + 1)
ICON_GRID_POINTS = 2_949_120


def icon_forecast_cycle(at: datetime) -> tuple[datetime, int]:
    if at.tzinfo is None:
        raise ValueError("Forecast time must include a timezone")
    target = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    if at.minute >= 30:
        target += timedelta(hours=1)
    available = at.astimezone(UTC) - timedelta(hours=3)
    cycle = available.replace(
        hour=available.hour // 6 * 6, minute=0, second=0, microsecond=0
    )
    return cycle, round((target - cycle) / timedelta(hours=1))


def icon_cloud_url(cycle: datetime, forecast_hour: int, level: int) -> str:
    return (
        f"{ICON_BASE_URL}/{cycle:%H}/clc/"
        f"icon_global_icosahedral_model-level_{cycle:%Y%m%d%H}_"
        f"{forecast_hour:03d}_{level}_CLC.grib2.bz2"
    )


def icon_height_url(cycle: datetime, level: int) -> str:
    return (
        f"{ICON_BASE_URL}/{cycle:%H}/hhl/"
        f"icon_global_icosahedral_time-invariant_{cycle:%Y%m%d%H}_"
        f"{level}_HHL.grib2.bz2"
    )


def icon_source_indices(
    cache_dir: Path, fetch: Callable[[str], bytes]
) -> NDArray[np.int32]:
    path = cache_dir / "north_america_pacific_source_indices.npy"
    if path.exists():
        indices = np.load(path)
    else:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(
            fileobj=BytesIO(fetch(ICON_WEIGHTS_URL)), mode="r:bz2"
        ) as tar:
            member = tar.extractfile(ICON_WEIGHTS_MEMBER)
            if member is None:
                raise ValueError("ICON remapping package has no weights")
            with TemporaryDirectory(prefix="skylight-icon-weights-") as directory:
                weights_path = Path(directory) / "weights.nc"
                with weights_path.open("wb") as output:
                    while block := member.read(1 << 20):
                        output.write(block)
                with Dataset(weights_path) as weights:
                    destination_shape = tuple(
                        int(value) for value in weights["dst_grid_dims"][:]
                    )
                    if destination_shape != (1440, 721):
                        raise ValueError("Unexpected ICON target grid shape")
                    addresses = np.asarray(weights["src_address"][:], dtype=np.int32)
                    destinations = np.asarray(weights["dst_address"][:], dtype=np.int32)
                    if not np.array_equal(
                        destinations, np.arange(1, len(destinations) + 1)
                    ):
                        raise ValueError(
                            "ICON remapping addresses are not in grid order"
                        )
        rows = np.arange(
            int((NORTH + 90) / GRID_STEP), int((SOUTH + 90) / GRID_STEP) - 1, -1
        )
        columns = np.arange(int(WEST / GRID_STEP), int(EAST / GRID_STEP) + 1)
        indices = addresses.reshape(721, 1440)[np.ix_(rows, columns)] - 1
        temporary_path = path.with_suffix(".tmp.npy")
        np.save(temporary_path, indices)
        temporary_path.replace(path)
    if (
        indices.shape != GRID_SHAPE
        or indices.min() < 0
        or indices.max() >= ICON_GRID_POINTS
    ):
        raise ValueError("Invalid ICON source index cache")
    return indices


def read_icon_field(
    url: str,
    level: int,
    short_name: str,
    indices: NDArray[np.int32],
    fetch: Callable[[str], bytes],
) -> tuple[NDArray[np.float32], datetime]:
    with TemporaryDirectory(prefix="skylight-icon-field-") as directory:
        path = Path(directory) / "field.grib2"
        path.write_bytes(bz2.decompress(fetch(url)))
        with path.open("rb") as stream:
            message = codes_grib_new_from_file(stream)
            if message is None:
                raise ValueError(f"ICON field is empty: {url}")
            if (
                codes_get(message, "shortName") != short_name
                or codes_get(message, "level") != level
                or codes_get(message, "numberOfPoints") != ICON_GRID_POINTS
            ):
                codes_release(message)
                raise ValueError(f"Unexpected ICON field: {url}")
            values = np.asarray(codes_get_values(message)[indices], dtype=np.float32)
            date = str(codes_get(message, "validityDate"))
            time = int(codes_get(message, "validityTime"))
            codes_release(message)
    valid_time = datetime.strptime(f"{date}{time:04d}", "%Y%m%d%H%M").replace(
        tzinfo=UTC
    )
    return values, valid_time


def icon_level_heights(
    cycle: datetime,
    indices: NDArray[np.int32],
    cache_dir: Path,
    fetch: Callable[[str], bytes],
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    path = cache_dir / "north_america_pacific_level_heights_dense_high.npz"
    if path.exists():
        with np.load(path) as cached:
            centers = np.asarray(cached["centers_km"], dtype=np.float32)
            terrain = np.asarray(cached["terrain_km"], dtype=np.float32)
    else:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(
                    read_icon_field,
                    icon_height_url(cycle, level),
                    level,
                    "HHL",
                    indices,
                    fetch,
                )
                for level in ICON_HALF_LEVELS
            ]
            boundaries = {
                level: future.result()[0]
                for level, future in zip(ICON_HALF_LEVELS, futures, strict=True)
            }
        centers = np.stack(
            [
                (boundaries[level - 1] + boundaries[level]) / 2000
                for level in ICON_MODEL_LEVELS
            ]
        ).astype(np.float32)
        terrain = (boundaries[120] / 1000).astype(np.float32)
        temporary_path = path.with_suffix(".tmp.npz")
        np.savez_compressed(temporary_path, centers_km=centers, terrain_km=terrain)
        temporary_path.replace(path)
    if (
        centers.shape != (len(ICON_MODEL_LEVELS), *GRID_SHAPE)
        or terrain.shape != GRID_SHAPE
    ):
        raise ValueError("Invalid ICON height cache")
    return centers, terrain


def cloud_by_altitude(
    cloud_percent: NDArray[np.float32],
    centers_km: NDArray[np.float32],
    terrain_km: NDArray[np.float32],
    altitudes_km: NDArray[np.float64],
) -> NDArray[np.float32]:
    cloud = cloud_percent[::-1] / 100
    heights = centers_km[::-1]
    if not np.all(np.diff(heights, axis=0) > 0):
        raise ValueError("ICON cloud layer heights must increase with altitude")
    volume = np.empty((len(altitudes_km), *terrain_km.shape), dtype=np.float32)
    for index, altitude in enumerate(altitudes_km):
        lower = np.clip(np.sum(heights <= altitude, axis=0) - 1, 0, len(heights) - 2)
        upper = lower + 1
        low_height = np.take_along_axis(heights, lower[None], axis=0)[0]
        high_height = np.take_along_axis(heights, upper[None], axis=0)[0]
        low_cloud = np.take_along_axis(cloud, lower[None], axis=0)[0]
        high_cloud = np.take_along_axis(cloud, upper[None], axis=0)[0]
        fraction = np.clip((altitude - low_height) / (high_height - low_height), 0, 1)
        volume[index] = low_cloud + fraction * (high_cloud - low_cloud)
        volume[index, terrain_km > altitude] = 0
    return np.clip(volume, 0, 1)


def load_cloud_volume(
    at: datetime,
    fetch: Callable[[str], bytes] = fetch_bytes,
    cache_dir: Path = ICON_CACHE_DIR,
) -> CloudVolume:
    cycle, forecast_hour = icon_forecast_cycle(at)
    indices = icon_source_indices(cache_dir, fetch)
    centers_km, terrain_km = icon_level_heights(cycle, indices, cache_dir, fetch)
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                read_icon_field,
                icon_cloud_url(cycle, forecast_hour, level),
                level,
                "ccl",
                indices,
                fetch,
            )
            for level in ICON_MODEL_LEVELS
        ]
        fields = [future.result() for future in futures]
    valid_times = {valid_time for _, valid_time in fields}
    expected_time = cycle + timedelta(hours=forecast_hour)
    if valid_times != {expected_time}:
        raise ValueError(f"ICON fields have unexpected valid times: {valid_times}")
    altitudes_km = np.arange(0.5, 16.1, 0.5)
    cloud_fraction = cloud_by_altitude(
        np.stack([values for values, _ in fields]),
        centers_km,
        terrain_km,
        altitudes_km,
    )
    return CloudVolume(
        cloud_fraction=cloud_fraction,
        latitudes=np.arange(NORTH, SOUTH - GRID_STEP / 2, -GRID_STEP),
        longitudes=np.arange(WEST, EAST + GRID_STEP / 2, GRID_STEP),
        altitudes_km=altitudes_km,
        valid_time=expected_time,
        source_url=f"{ICON_BASE_URL}/{cycle:%H}/clc/",
    )
