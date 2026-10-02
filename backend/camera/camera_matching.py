from dataclasses import dataclass
from math import asin, cos, degrees, floor, radians
from typing import Any

from pyproj import Geod

from backend.camera.camera_models import Camera

EARTH_RADIUS_KM = 6371.0088
MAX_VIEW_DISTANCE_KM = 100.0
GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class MatchedCamera:
    camera: Camera
    event_ids: tuple[str, ...]


def cell(latitude: float, longitude: float) -> tuple[int, int]:
    return floor(latitude), floor(longitude) % 360


def faces_circle(camera: Camera, circle: dict[str, float]) -> bool:
    bearing, _, distance_m = GEOD.inv(
        camera.longitude,
        camera.latitude,
        circle["center_longitude"],
        circle["center_latitude"],
    )
    distance_km = distance_m / 1000
    radius_km = circle["radius_km"]
    if distance_km > radius_km + MAX_VIEW_DISTANCE_KM:
        return False
    if camera.sky_facing:
        return True
    if camera.azimuth_degrees is None or camera.bearing_tolerance_degrees is None:
        raise ValueError("Camera direction and tolerance are required for matching")
    if distance_km <= radius_km:
        return True
    target_half_width = degrees(asin(radius_km / distance_km))
    heading_difference = abs((bearing - camera.azimuth_degrees + 180) % 360 - 180)
    return heading_difference <= camera.bearing_tolerance_degrees + target_half_width


def match_cameras(
    storms: dict[str, Any], cameras: list[Camera], include_sky_facing: bool = False
) -> list[MatchedCamera]:
    matches: list[list[str]] = [[] for _ in cameras]
    camera_cells: dict[tuple[int, int], list[int]] = {}
    for index, camera in enumerate(cameras):
        if (camera.azimuth_degrees is None) != (
            camera.bearing_tolerance_degrees is None
        ):
            raise ValueError("Camera direction and tolerance must be provided together")
        if camera.azimuth_degrees is None and not (
            include_sky_facing and camera.sky_facing
        ):
            continue
        camera_cells.setdefault(cell(camera.latitude, camera.longitude), []).append(
            index
        )

    for feature in storms["features"]:
        circle = feature["properties"]["view_circle"]
        latitude_span = (
            degrees((circle["radius_km"] + MAX_VIEW_DISTANCE_KM) / EARTH_RADIUS_KM) + 1
        )
        maximum_latitude = min(89.0, abs(circle["center_latitude"]) + latitude_span)
        longitude_span = min(180.0, latitude_span / cos(radians(maximum_latitude)))
        longitude_cells = (
            range(360)
            if longitude_span == 180.0
            else range(
                floor(circle["center_longitude"] - longitude_span),
                floor(circle["center_longitude"] + longitude_span) + 1,
            )
        )
        for latitude_cell in range(
            floor(circle["center_latitude"] - latitude_span),
            floor(circle["center_latitude"] + latitude_span) + 1,
        ):
            for longitude_cell in longitude_cells:
                for camera_index in camera_cells.get(
                    (latitude_cell, longitude_cell % 360), ()
                ):
                    if faces_circle(cameras[camera_index], circle):
                        matches[camera_index].append(feature["properties"]["id"])

    return [
        MatchedCamera(camera, tuple(event_ids))
        for camera, event_ids in zip(cameras, matches, strict=True)
    ]
