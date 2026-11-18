from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pyproj import Geod

from backend.phenomena.event_geometry import EventCircle, enclosing_circle
from backend.phenomena.icon_weather import (
    GRID_SHAPE,
    GRID_STEP,
    ICON_BASE_URL,
    ICON_CACHE_DIR,
    NORTH,
    WEST,
    icon_forecast_cycle,
    icon_level_heights,
    icon_source_indices,
    read_icon_field,
)

PRESSURE_LEVELS_HPA = (850, 700, 500)
WGS84 = Geod(ellps="WGS84")

type WeatherGrids = dict[str, NDArray[np.float32]]
type WeatherFeatures = dict[str, float | None]


@dataclass(frozen=True)
class IconField:
    column: str
    directory: str
    level_type: str
    file_suffix: str
    level: int
    short_name: str

    def url(self, cycle: datetime, forecast_hour: int) -> str:
        return (
            f"{ICON_BASE_URL}/{cycle:%H}/{self.directory}/"
            f"icon_global_icosahedral_{self.level_type}_{cycle:%Y%m%d%H}_"
            f"{forecast_hour:03d}_{self.file_suffix}.grib2.bz2"
        )


def pressure_field(
    name: str, unit: str, directory: str, short_name: str, level: int
) -> IconField:
    return IconField(
        column=f"icon_{name}_{level}hpa_{unit}",
        directory=directory,
        level_type="pressure-level",
        file_suffix=f"{level}_{directory.upper()}",
        level=level,
        short_name=short_name,
    )


def cloud_cover_field(layer: str, directory: str, level: int) -> IconField:
    return IconField(
        column=f"icon_{layer}_cloud_cover_percent",
        directory=directory,
        level_type="single-level",
        file_suffix=directory.upper(),
        level=level,
        short_name=directory.upper(),
    )


ICON_FIELDS = (
    *(
        field
        for level in PRESSURE_LEVELS_HPA
        for field in (
            pressure_field("eastward_wind", "ms", "u", "u", level),
            pressure_field("northward_wind", "ms", "v", "v", level),
            pressure_field("temperature", "kelvin", "t", "t", level),
            pressure_field("relative_humidity", "percent", "relhum", "r", level),
        )
    ),
    cloud_cover_field("total", "clct", 0),
    cloud_cover_field("low", "clcl", 800),
    cloud_cover_field("mid", "clcm", 400),
    cloud_cover_field("high", "clch", 0),
)
TERRAIN_COLUMN = "icon_terrain_height_km"
STORM_COLUMNS = (
    "nearest_storm_distance_km",
    "nearest_storm_bearing_degrees",
    "nearest_storm_radius_km",
    "nearest_storm_severe_probability_percent",
    "nearest_storm_motion_east",
    "nearest_storm_motion_south",
)
WEATHER_COLUMNS = (
    *(field.column for field in ICON_FIELDS),
    TERRAIN_COLUMN,
    *STORM_COLUMNS,
)


def load_weather_grids(
    at: datetime, fetch: Callable[[str], bytes], cache_dir: Path = ICON_CACHE_DIR
) -> WeatherGrids:
    cycle, forecast_hour = icon_forecast_cycle(at)
    indices = icon_source_indices(cache_dir, fetch)
    terrain_km = icon_level_heights(cycle, indices, cache_dir, fetch)[1]
    with ThreadPoolExecutor(max_workers=8) as executor:
        reads = [
            executor.submit(
                read_icon_field,
                field.url(cycle, forecast_hour),
                field.level,
                field.short_name,
                indices,
                fetch,
            )
            for field in ICON_FIELDS
        ]
        grids = {
            field.column: read.result()[0] for field, read in zip(ICON_FIELDS, reads)
        }
    return grids | {TERRAIN_COLUMN: terrain_km}


def grid_cell(latitude: float, longitude: float) -> tuple[int, int] | None:
    row = round((NORTH - latitude) / GRID_STEP)
    column = round((longitude % 360 - WEST) / GRID_STEP)
    if not (0 <= row < GRID_SHAPE[0] and 0 <= column < GRID_SHAPE[1]):
        return None
    return row, column


def icon_features(
    grids: WeatherGrids, latitude: float, longitude: float
) -> WeatherFeatures:
    cell = grid_cell(latitude, longitude)
    if cell is None:
        return dict.fromkeys(grids)
    return {column: round(float(grid[cell]), 2) for column, grid in grids.items()}


def terrain_relief_km(
    terrain_km: NDArray[np.float32],
    latitude: float,
    longitude: float,
    radius_cells: int,
) -> float | None:
    cell = grid_cell(latitude, longitude)
    if cell is None:
        return None
    row, column = cell
    window = terrain_km[
        max(row - radius_cells, 0) : row + radius_cells + 1,
        max(column - radius_cells, 0) : column + radius_cells + 1,
    ]
    return round(float(window.max() - window.min()), 2)


@dataclass(frozen=True)
class Storm:
    circle: EventCircle
    severe_probability_percent: int
    motion_east: float | None
    motion_south: float | None


def optional_float(value: str | None) -> float | None:
    return None if value is None else float(value)


def probsevere_storms(probsevere: dict[str, Any]) -> list[Storm]:
    return [
        Storm(
            circle=enclosing_circle(feature["geometry"]),
            severe_probability_percent=int(feature["models"]["probsevere"]["PROB"]),
            motion_east=optional_float(feature["properties"].get("MOTION_EAST")),
            motion_south=optional_float(feature["properties"].get("MOTION_SOUTH")),
        )
        for feature in probsevere["features"]
    ]


def nearest_storm_features(
    storms: list[Storm], latitude: float, longitude: float
) -> WeatherFeatures:
    if not storms:
        return dict.fromkeys(STORM_COLUMNS)
    bearings, _, distances_m = WGS84.inv(
        np.full(len(storms), longitude),
        np.full(len(storms), latitude),
        np.array([storm.circle.center_longitude for storm in storms]),
        np.array([storm.circle.center_latitude for storm in storms]),
    )
    nearest = int(np.argmin(distances_m))
    return {
        "nearest_storm_distance_km": round(float(distances_m[nearest]) / 1000, 1),
        "nearest_storm_bearing_degrees": round(float(bearings[nearest]) % 360, 1),
        "nearest_storm_radius_km": storms[nearest].circle.radius_km,
        "nearest_storm_severe_probability_percent": storms[
            nearest
        ].severe_probability_percent,
        "nearest_storm_motion_east": storms[nearest].motion_east,
        "nearest_storm_motion_south": storms[nearest].motion_south,
    }
