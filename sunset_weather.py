from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

import numpy as np
from eccodes import codes_get, codes_get_values, codes_grib_new_from_file, codes_release
from numpy.typing import NDArray

from weather_source import fetch_bytes

AURORA_SOUTH, AURORA_NORTH, AURORA_WEST, AURORA_EAST = 35, 80, 180, 310


@dataclass(frozen=True)
class CloudCoverGrid:
    percentage: NDArray[np.float32]
    latitudes: NDArray[np.float64]
    longitudes: NDArray[np.float64]
    valid_time: datetime
    source_url: str


def forecast_cycle(at: datetime) -> tuple[datetime, int]:
    if at.tzinfo is None:
        raise ValueError("Forecast time must include a timezone")
    target = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    if at.minute >= 30:
        target += timedelta(hours=1)
    available = target - timedelta(hours=4)
    cycle = available.replace(hour=available.hour // 6 * 6)
    return cycle, round((target - cycle) / timedelta(hours=1))


def gfs_filter_url(
    cycle: datetime,
    forecast_hour: int,
    bounds: tuple[int, int, int, int],
    levels: tuple[str, ...],
) -> str:
    south, north, west, east = bounds
    query: dict[str, str] = {
        "file": f"gfs.t{cycle:%H}z.pgrb2.0p25.f{forecast_hour:03d}",
        "var_TCDC": "on",
        "var_HGT": "on",
        "subregion": "",
        "leftlon": str(west),
        "rightlon": str(east),
        "toplat": str(north),
        "bottomlat": str(south),
        "dir": f"/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos",
    }
    query.update({f"lev_{level}": "on" for level in levels})
    return "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?" + urlencode(query)


def gfs_total_cloud_url(cycle: datetime, forecast_hour: int) -> str:
    return gfs_filter_url(
        cycle,
        forecast_hour,
        (AURORA_SOUTH, AURORA_NORTH, AURORA_WEST, AURORA_EAST),
        ("entire_atmosphere",),
    )


def read_total_cloud_cover(payload: bytes, source_url: str) -> CloudCoverGrid:
    with TemporaryDirectory(prefix="skylight-aurora-cloud-") as directory:
        path = Path(directory) / "clouds.grib2"
        path.write_bytes(payload)
        with path.open("rb") as stream:
            selected = False
            while message := codes_grib_new_from_file(stream):
                if codes_get(message, "shortName") != "tcc":
                    codes_release(message)
                    raise ValueError("Expected GFS total cloud cover")
                if codes_get(message, "stepType") != "instant":
                    codes_release(message)
                    continue
                if selected:
                    codes_release(message)
                    raise ValueError("Expected one instantaneous GFS cloud field")
                rows = codes_get(message, "Nj")
                columns = codes_get(message, "Ni")
                percentage = (
                    codes_get_values(message).reshape(rows, columns).astype(np.float32)
                )
                first_latitude = codes_get(message, "latitudeOfFirstGridPointInDegrees")
                first_longitude = codes_get(
                    message, "longitudeOfFirstGridPointInDegrees"
                )
                latitude_step = codes_get(message, "jDirectionIncrementInDegrees")
                longitude_step = codes_get(message, "iDirectionIncrementInDegrees")
                if codes_get(message, "jScansPositively"):
                    percentage = percentage[::-1]
                    north = first_latitude + (rows - 1) * latitude_step
                else:
                    north = first_latitude
                if codes_get(message, "iScansNegatively"):
                    percentage = percentage[:, ::-1]
                    west = first_longitude - (columns - 1) * longitude_step
                else:
                    west = first_longitude
                date = str(codes_get(message, "validityDate"))
                time = int(codes_get(message, "validityTime"))
                valid_time = datetime.strptime(
                    f"{date}{time:04d}", "%Y%m%d%H%M"
                ).replace(tzinfo=UTC)
                codes_release(message)
                selected = True
            if not selected:
                raise ValueError("GFS response has no instantaneous cloud field")
    return CloudCoverGrid(
        percentage=percentage,
        latitudes=north - np.arange(rows) * latitude_step,
        longitudes=west + np.arange(columns) * longitude_step,
        valid_time=valid_time,
        source_url=source_url,
    )


def load_total_cloud_cover(at: datetime, available_at: datetime) -> CloudCoverGrid:
    target_cycle, target_hour = forecast_cycle(at)
    target_time = target_cycle + timedelta(hours=target_hour)
    cycle, _ = forecast_cycle(available_at)
    forecast_hour = round((target_time - cycle) / timedelta(hours=1))
    source_url = gfs_total_cloud_url(cycle, forecast_hour)
    return read_total_cloud_cover(fetch_bytes(source_url), source_url)
