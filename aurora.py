from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import floor
from typing import Any

import numpy as np
from scipy.ndimage import map_coordinates

from camera_matching import MatchedCamera, match_cameras
from cameras import Camera
from event_geometry import enclosing_circle
from sunset_scoring import solar_geometry
from sunset_weather import CloudCoverGrid
from weather_source import parse_utc_time

OVATION_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
MINIMUM_AURORA_PERCENT = 20
MAXIMUM_CLOUD_PERCENT = 30
TILE_DEGREES = 4
MAXIMUM_FORECAST_AGE = timedelta(hours=2)


@dataclass(frozen=True)
class AuroraCamera:
    event_ids: tuple[str, ...]
    cloud_cover_percent: int | None
    dark: bool


@dataclass(frozen=True)
class AuroraEvents:
    features: dict[str, Any]
    cameras: tuple[AuroraCamera, ...]
    observation_time: str
    forecast_time: str
    cloud_time: str
    cloud_source_url: str


def cloud_cover_at(
    cloud: CloudCoverGrid, latitudes: np.ndarray, longitudes: np.ndarray
) -> np.ndarray:
    latitude_index = (cloud.latitudes[0] - latitudes) / 0.25
    longitude_index = ((longitudes % 360) - cloud.longitudes[0]) / 0.25
    return map_coordinates(
        cloud.percentage,
        (latitude_index, longitude_index),
        order=1,
        mode="constant",
        cval=np.nan,
    )


def dark_at(at: datetime, latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    elevation, _, _, _ = solar_geometry(at, latitudes, longitudes)
    return elevation <= -6


def cell_polygon(latitude: int, longitude: int) -> list[list[list[float]]]:
    west = longitude - 0.5
    east = longitude + 0.5
    south = latitude - 0.5
    north = latitude + 0.5
    return [
        [
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]
    ]


def classify_auroras(
    data: dict[str, Any], cloud: CloudCoverGrid, cameras: list[Camera], now: datetime
) -> AuroraEvents:
    if data["Data Format"] != "[Longitude, Latitude, Aurora]":
        raise ValueError("Unexpected OVATION coordinate format")
    observation_time = parse_utc_time(data["Observation Time"])
    forecast_time = parse_utc_time(data["Forecast Time"])
    if now.astimezone(UTC) - forecast_time > MAXIMUM_FORECAST_AGE:
        raise ValueError("OVATION forecast is stale")
    if abs(cloud.valid_time - forecast_time) > timedelta(hours=1):
        raise ValueError("GFS cloud cover is not aligned with OVATION forecast")

    coordinates = np.asarray(data["coordinates"], dtype=np.float64)
    if coordinates.ndim != 2 or coordinates.shape[1] != 3:
        raise ValueError("OVATION coordinates must contain longitude, latitude, aurora")
    longitudes = (coordinates[:, 0] + 180) % 360 - 180
    latitudes = coordinates[:, 1]
    probabilities = coordinates[:, 2]
    in_coverage = (
        (latitudes >= cloud.latitudes[-1] + 0.5)
        & (latitudes <= cloud.latitudes[0] - 0.5)
        & (longitudes >= -180.0 + 0.5)
        & (longitudes <= -50.0 - 0.5)
    )
    eligible = in_coverage & (probabilities >= MINIMUM_AURORA_PERCENT)
    candidate_latitudes = latitudes[eligible]
    candidate_longitudes = longitudes[eligible]
    candidate_probabilities = probabilities[eligible]
    cover = cloud_cover_at(cloud, candidate_latitudes, candidate_longitudes)
    nighttime = dark_at(forecast_time, candidate_latitudes, candidate_longitudes)

    tiles: dict[tuple[int, int], list[tuple[int, int, int, int]]] = defaultdict(list)
    for latitude, longitude, probability, cloud_percent, dark in zip(
        candidate_latitudes,
        candidate_longitudes,
        candidate_probabilities,
        cover,
        nighttime,
        strict=True,
    ):
        if (
            not dark
            or not np.isfinite(cloud_percent)
            or cloud_percent > MAXIMUM_CLOUD_PERCENT
        ):
            continue
        lat, lon = int(latitude), int(longitude)
        key = floor(lat / TILE_DEGREES), floor((lon + 180) / TILE_DEGREES)
        tiles[key].append((lat, lon, int(probability), round(float(cloud_percent))))

    features = []
    for key, cells in sorted(tiles.items()):
        geometry = {
            "type": "MultiPolygon",
            "coordinates": [cell_polygon(lat, lon) for lat, lon, _, _ in cells],
        }
        circle = enclosing_circle(geometry)
        probability = max(value for _, _, value, _ in cells)
        cloud_percent = round(sum(value for _, _, _, value in cells) / len(cells))
        identifier = f"aurora-{key[0]}-{key[1]}"
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "id": identifier,
                    "kind": "aurora",
                    "valid_time": forecast_time.isoformat(timespec="minutes"),
                    "observation_time": observation_time.isoformat(timespec="minutes"),
                    "source_url": OVATION_URL,
                    "cloud_source_url": cloud.source_url,
                    "cloud_valid_time": cloud.valid_time.isoformat(timespec="minutes"),
                    "circle": asdict(circle),
                    "view_circle": asdict(circle),
                    "interestingness": {
                        "score": round(probability * (1 - cloud_percent / 100), 1),
                        "aurora_percent": probability,
                        "cloud_cover_percent": cloud_percent,
                    },
                    "aurora_percent": probability,
                    "cloud_cover_percent": cloud_percent,
                },
            }
        )

    collection = {"type": "FeatureCollection", "features": features}
    matches: list[MatchedCamera] = match_cameras(collection, cameras)
    camera_latitudes = np.asarray(
        [camera.latitude for camera in cameras], dtype=np.float64
    )
    camera_longitudes = np.asarray(
        [camera.longitude for camera in cameras], dtype=np.float64
    )
    camera_cover = cloud_cover_at(cloud, camera_latitudes, camera_longitudes)
    camera_dark = dark_at(forecast_time, camera_latitudes, camera_longitudes)
    camera_results = tuple(
        AuroraCamera(
            event_ids=match.event_ids
            if dark
            and np.isfinite(cover_percent)
            and cover_percent <= MAXIMUM_CLOUD_PERCENT
            else (),
            cloud_cover_percent=round(float(cover_percent))
            if np.isfinite(cover_percent)
            else None,
            dark=bool(dark),
        )
        for match, cover_percent, dark in zip(
            matches, camera_cover, camera_dark, strict=True
        )
    )
    return AuroraEvents(
        features=collection,
        cameras=camera_results,
        observation_time=observation_time.isoformat(timespec="minutes"),
        forecast_time=forecast_time.isoformat(timespec="minutes"),
        cloud_time=cloud.valid_time.isoformat(timespec="minutes"),
        cloud_source_url=cloud.source_url,
    )
