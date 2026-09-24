import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from gzip import decompress
from math import ceil, cos, degrees, floor, radians
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from urllib.parse import urlencode, urljoin
from xml.etree import ElementTree

import numpy as np
from eccodes import codes_get, codes_get_values, codes_new_from_message, codes_release
from netCDF4 import Dataset
from numpy.typing import NDArray
from pyproj import CRS, Transformer

MRMS_DIRECTORY = "https://mrms.ncep.noaa.gov/2D/ReflectivityAtLowestAltitude/"
MRMS_LATEST = urljoin(
    MRMS_DIRECTORY, "MRMS_ReflectivityAtLowestAltitude.latest.grib2.gz"
)
MRMS_FILENAME = re.compile(
    r"MRMS_ReflectivityAtLowestAltitude_00\.50_(\d{8}-\d{6})\.grib2\.gz"
)
GOES_FILENAME_TIME = re.compile(r"_s(\d{13})\d*_e")
S3_NAMESPACE = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}

type FetchText = Callable[[str], str]


@dataclass(frozen=True)
class RadarGrid:
    reflectivity_dbz: NDArray[np.float64]
    north_edge: float
    west_edge: float
    latitude_step: float
    longitude_step: float
    missing_value: float
    valid_time: datetime
    source_url: str


@dataclass(frozen=True)
class CloudGrid:
    cloud_level: NDArray[np.uint8]
    quality: NDArray[np.uint8]
    x_axis: NDArray[np.float32]
    y_axis: NDArray[np.float32]
    transformer: Transformer
    perspective_height: float
    valid_time: datetime
    source_url: str


@dataclass(frozen=True)
class CloudPropertyGrid:
    values: NDArray[np.float64]
    valid: NDArray[np.bool_]
    x_axis: NDArray[np.float32]
    y_axis: NDArray[np.float32]
    transformer: Transformer
    perspective_height: float
    valid_time: datetime
    source_url: str


class GoesPixelGrid(Protocol):
    @property
    def x_axis(self) -> NDArray[np.float32]: ...

    @property
    def y_axis(self) -> NDArray[np.float32]: ...

    @property
    def transformer(self) -> Transformer: ...

    @property
    def perspective_height(self) -> float: ...


def mrms_source(at: datetime | None, fetch_text: FetchText) -> str:
    if at is None:
        return MRMS_LATEST

    cutoff = at.strftime("%Y%m%d-%H%M%S")
    timestamps = {
        timestamp
        for timestamp in MRMS_FILENAME.findall(fetch_text(MRMS_DIRECTORY))
        if timestamp <= cutoff
    }
    if not timestamps:
        raise ValueError(f"No MRMS radar snapshot found at or before {at}")
    return urljoin(
        MRMS_DIRECTORY,
        f"MRMS_ReflectivityAtLowestAltitude_00.50_{max(timestamps)}.grib2.gz",
    )


def goes_source(
    at: datetime, longitude: float, fetch_text: FetchText, product: str = "ACMC"
) -> str:
    satellite = 18 if longitude < -110 else 19
    bucket = f"https://noaa-goes{satellite}.s3.amazonaws.com/"
    keys = []
    for hour in (at - timedelta(hours=1), at):
        prefix = f"ABI-L2-{product}/{hour:%Y}/{hour:%j}/{hour:%H}/"
        listing_url = f"{bucket}?{urlencode({'list-type': '2', 'prefix': prefix, 'max-keys': '1000'})}"
        root = ElementTree.fromstring(fetch_text(listing_url))
        if root.findtext("s:IsTruncated", namespaces=S3_NAMESPACE) != "false":
            raise ValueError(f"GOES listing is incomplete: {listing_url}")
        for item in root.findall("s:Contents", S3_NAMESPACE):
            key = item.findtext("s:Key", namespaces=S3_NAMESPACE)
            if key is None:
                raise ValueError("GOES listing entry has no key")
            match = GOES_FILENAME_TIME.search(key)
            if match is None:
                raise ValueError(f"GOES key has no scan time: {key}")
            scan_time = datetime.strptime(match.group(1), "%Y%j%H%M%S").replace(
                tzinfo=UTC
            )
            if scan_time <= at:
                keys.append((scan_time, key))
    if not keys:
        raise ValueError(f"No GOES-{satellite} {product} found at or before {at}")
    return urljoin(bucket, max(keys)[1])


def local_bounds(
    latitude: float, longitude: float, radius_km: float
) -> tuple[float, float, float, float]:
    if radius_km <= 0:
        raise ValueError("Window radius must be positive")
    latitude_span = degrees(radius_km / 6371.0088)
    longitude_span = degrees(radius_km / (6371.0088 * cos(radians(latitude))))
    return (
        latitude - latitude_span,
        latitude + latitude_span,
        longitude - longitude_span,
        longitude + longitude_span,
    )


def read_mrms_grid(payload: bytes, source_url: str) -> RadarGrid:
    message = codes_new_from_message(decompress(payload))
    rows = codes_get(message, "Nj")
    columns = codes_get(message, "Ni")
    grid = RadarGrid(
        reflectivity_dbz=codes_get_values(message).reshape(rows, columns),
        north_edge=codes_get(message, "latitudeOfFirstGridPointInDegrees"),
        west_edge=codes_get(message, "longitudeOfFirstGridPointInDegrees"),
        latitude_step=codes_get(message, "jDirectionIncrementInDegrees"),
        longitude_step=codes_get(message, "iDirectionIncrementInDegrees"),
        missing_value=codes_get(message, "missingValue"),
        valid_time=datetime(
            codes_get(message, "year"),
            codes_get(message, "month"),
            codes_get(message, "day"),
            codes_get(message, "hour"),
            codes_get(message, "minute"),
            codes_get(message, "second"),
            tzinfo=UTC,
        ),
        source_url=source_url,
    )
    codes_release(message)
    return grid


def mrms_mask(
    grid: RadarGrid,
    latitude: float,
    longitude: float,
    radius_km: float,
    reflectivity_dbz: float,
) -> NDArray[np.bool_]:
    south, north, west, east = local_bounds(latitude, longitude, radius_km)
    west = west % 360
    east = east % 360
    row_start = floor((grid.north_edge - north) / grid.latitude_step)
    row_end = ceil((grid.north_edge - south) / grid.latitude_step)
    column_start = floor((west - grid.west_edge) / grid.longitude_step)
    column_end = ceil((east - grid.west_edge) / grid.longitude_step)
    rows, columns = grid.reflectivity_dbz.shape
    if not (0 <= row_start < row_end <= rows):
        raise ValueError("Requested latitude window is outside MRMS coverage")
    if not (0 <= column_start < column_end <= columns):
        raise ValueError("Requested longitude window is outside MRMS coverage")

    region = grid.reflectivity_dbz[row_start:row_end, column_start:column_end]
    return (region >= reflectivity_dbz) & (region != grid.missing_value)


def read_goes_grid(payload: bytes, source_url: str) -> CloudGrid:
    with TemporaryDirectory(prefix="skylight-goes-") as directory:
        path = Path(directory) / "cloud.nc"
        path.write_bytes(payload)
        with Dataset(path) as data:
            data.set_auto_mask(False)
            projection = data.variables["goes_imager_projection"]
            crs = CRS.from_cf(
                {name: projection.getncattr(name) for name in projection.ncattrs()}
            )
            return CloudGrid(
                cloud_level=data.variables["ACM"][:],
                quality=data.variables["DQF"][:],
                x_axis=data.variables["x"][:],
                y_axis=data.variables["y"][:],
                transformer=Transformer.from_crs("EPSG:4326", crs, always_xy=True),
                perspective_height=projection.perspective_point_height,
                valid_time=datetime.fromisoformat(data.time_coverage_start),
                source_url=source_url,
            )


def read_goes_property(payload: bytes, source_url: str, name: str) -> CloudPropertyGrid:
    if name not in {"HT", "COD"}:
        raise ValueError(f"Unsupported GOES cloud property: {name}")
    with TemporaryDirectory(prefix="skylight-goes-property-") as directory:
        path = Path(directory) / "cloud.nc"
        path.write_bytes(payload)
        with Dataset(path) as data:
            data.set_auto_mask(False)
            projection = data.variables["goes_imager_projection"]
            crs = CRS.from_cf(
                {
                    attribute: projection.getncattr(attribute)
                    for attribute in projection.ncattrs()
                }
            )
            variable = data.variables[name]
            variable.set_auto_maskandscale(False)
            raw = variable[:]
            quality = data.variables["DQF"][:]
            good_quality = quality == 0 if name == "HT" else (quality & 4) == 0
            return CloudPropertyGrid(
                values=raw * variable.scale_factor + variable.add_offset,
                valid=(raw != variable._FillValue) & good_quality,
                x_axis=data.variables["x"][:],
                y_axis=data.variables["y"][:],
                transformer=Transformer.from_crs("EPSG:4326", crs, always_xy=True),
                perspective_height=projection.perspective_point_height,
                valid_time=datetime.fromisoformat(data.time_coverage_start),
                source_url=source_url,
            )


def goes_pixel_bounds(
    grid: GoesPixelGrid, south: float, north: float, west: float, east: float
) -> tuple[slice, slice]:
    x_metres, y_metres = grid.transformer.transform(
        [west, east, west, east], [south, south, north, north]
    )
    x_radians = np.asarray(x_metres) / grid.perspective_height
    y_radians = np.asarray(y_metres) / grid.perspective_height
    if not (np.all(np.isfinite(x_radians)) and np.all(np.isfinite(y_radians))):
        raise ValueError("Requested window is outside GOES view")
    if x_radians.min() < grid.x_axis[0] or x_radians.max() > grid.x_axis[-1]:
        raise ValueError("Requested longitude window is outside GOES coverage")
    if y_radians.min() < grid.y_axis[-1] or y_radians.max() > grid.y_axis[0]:
        raise ValueError("Requested latitude window is outside GOES coverage")

    column_start = np.searchsorted(grid.x_axis, x_radians.min())
    column_end = np.searchsorted(grid.x_axis, x_radians.max())
    row_start = np.searchsorted(-grid.y_axis, -y_radians.max())
    row_end = np.searchsorted(-grid.y_axis, -y_radians.min())
    if not (0 <= column_start < column_end <= len(grid.x_axis)):
        raise ValueError("Requested longitude window is outside GOES coverage")
    if not (0 <= row_start < row_end <= len(grid.y_axis)):
        raise ValueError("Requested latitude window is outside GOES coverage")
    return slice(row_start, row_end), slice(column_start, column_end)


def goes_cloud_mask(
    grid: CloudGrid,
    latitude: float,
    longitude: float,
    radius_km: float,
) -> NDArray[np.bool_]:
    south, north, west, east = local_bounds(latitude, longitude, radius_km)
    rows, columns = goes_pixel_bounds(grid, south, north, west, east)
    cloud_level = grid.cloud_level[rows, columns]
    quality = grid.quality[rows, columns]
    return (cloud_level >= 2) & (cloud_level <= 3) & (quality == 0)
