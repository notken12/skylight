from dataclasses import dataclass
from math import hypot
from typing import Any

from pyproj import CRS, Transformer

from geojson_polygons import polygons_of

CIRCLE_BUFFER_KM = 5.0

type Point = tuple[float, float]


@dataclass(frozen=True)
class EventCircle:
    center_latitude: float
    center_longitude: float
    radius_km: float


def ring_area_centroid(ring: list[Point]) -> tuple[float, float, float]:
    twice_signed_area = 0.0
    longitude_moment = 0.0
    latitude_moment = 0.0
    for index, (x, y) in enumerate(ring):
        next_x, next_y = ring[(index + 1) % len(ring)]
        cross = x * next_y - next_x * y
        twice_signed_area += cross
        longitude_moment += (x + next_x) * cross
        latitude_moment += (y + next_y) * cross
    if twice_signed_area == 0:
        raise ValueError("Polygon ring area must be positive")
    return (
        abs(twice_signed_area) / 2,
        longitude_moment / (3 * twice_signed_area),
        latitude_moment / (3 * twice_signed_area),
    )


def polygon_area_centroid(
    polygon: list[list[Point]],
) -> tuple[float, float, float]:
    outer_area, outer_x, outer_y = ring_area_centroid(polygon[0])
    area = outer_area
    x_moment = outer_area * outer_x
    y_moment = outer_area * outer_y
    for hole in polygon[1:]:
        hole_area, hole_x, hole_y = ring_area_centroid(hole)
        area -= hole_area
        x_moment -= hole_area * hole_x
        y_moment -= hole_area * hole_y
    if area <= 0:
        raise ValueError("Polygon area must be positive")
    return area, x_moment / area, y_moment / area


def enclosing_circle(geometry: dict[str, Any]) -> EventCircle:
    polygons = polygons_of(geometry)
    outer_vertices = [point for polygon in polygons for point in polygon[0]]
    if not outer_vertices:
        raise ValueError("Shape must contain exterior vertices")
    reference_longitude = sum(point[0] for point in outer_vertices) / len(
        outer_vertices
    )
    reference_latitude = sum(point[1] for point in outer_vertices) / len(outer_vertices)
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={reference_latitude} +lon_0={reference_longitude} "
        "+datum=WGS84 +units=m +no_defs"
    )
    project = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    unproject = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    projected = [
        [
            [project.transform(longitude, latitude) for longitude, latitude in ring]
            for ring in polygon
        ]
        for polygon in polygons
    ]
    area_centroids = [polygon_area_centroid(polygon) for polygon in projected]
    total_area = sum(area for area, _, _ in area_centroids)
    center_x = sum(area * x for area, x, _ in area_centroids) / total_area
    center_y = sum(area * y for area, _, y in area_centroids) / total_area
    radius_m = max(
        hypot(x - center_x, y - center_y)
        for polygon in projected
        for x, y in polygon[0]
    )
    center_longitude, center_latitude = unproject.transform(center_x, center_y)
    return EventCircle(
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        radius_km=round(radius_m / 1000 + CIRCLE_BUFFER_KM, 1),
    )
