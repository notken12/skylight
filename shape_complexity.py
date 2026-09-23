from dataclasses import dataclass
from math import cos, pi, radians
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import find_objects, label
from skimage.measure import perimeter_crofton
from skimage.morphology import convex_hull_image

from geojson_polygons import polygons_of

EARTH_RADIUS_KM = 6371.0088

type Point = tuple[float, float]


@dataclass(frozen=True)
class ShapeComplexity:
    score: float
    jaggedness: float
    nonconvexity: float
    fragmentation: float
    component_count: int


def score_components(metrics: list[tuple[float, float, float]]) -> ShapeComplexity:
    if not metrics:
        return ShapeComplexity(0.0, 0.0, 0.0, 0.0, 0)

    total_area = sum(component_area for component_area, _, _ in metrics)
    jaggedness = (
        sum(
            component_area * component_jaggedness
            for component_area, component_jaggedness, _ in metrics
        )
        / total_area
    )
    nonconvexity = (
        sum(
            component_area * component_nonconvexity
            for component_area, _, component_nonconvexity in metrics
        )
        / total_area
    )
    fragmentation = (
        1 - max(component_area for component_area, _, _ in metrics) / total_area
    )
    return ShapeComplexity(
        score=round(100 * (jaggedness + nonconvexity + fragmentation) / 3, 1),
        jaggedness=round(jaggedness, 3),
        nonconvexity=round(nonconvexity, 3),
        fragmentation=round(fragmentation, 3),
        component_count=len(metrics),
    )


def area(points: list[Point]) -> float:
    return (
        abs(
            sum(
                x * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * y
                for index, (x, y) in enumerate(points)
            )
        )
        / 2
    )


def perimeter(points: list[Point]) -> float:
    return sum(
        (
            (x - points[(index + 1) % len(points)][0]) ** 2
            + (y - points[(index + 1) % len(points)][1]) ** 2
        )
        ** 0.5
        for index, (x, y) in enumerate(points)
    )


def convex_hull(points: list[Point]) -> list[Point]:
    vertices = sorted(set(points))
    if len(vertices) < 3:
        raise ValueError("A polygon needs at least three distinct vertices")

    def cross(origin: Point, first: Point, second: Point) -> float:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower: list[Point] = []
    for point in vertices:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[Point] = []
    for point in reversed(vertices):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return lower[:-1] + upper[:-1]


def polygon_metrics(polygon: list[list[list[float]]]) -> tuple[float, float, float]:
    outer_ring = polygon[0]
    reference_latitude = sum(point[1] for point in outer_ring) / len(outer_ring)
    latitude_scale = EARTH_RADIUS_KM * pi / 180
    longitude_scale = latitude_scale * cos(radians(reference_latitude))
    rings = [
        [
            (longitude * longitude_scale, latitude * latitude_scale)
            for longitude, latitude in ring
        ]
        for ring in polygon
    ]
    outer_area = area(rings[0])
    actual_area = outer_area - sum(area(ring) for ring in rings[1:])
    if actual_area <= 0:
        raise ValueError("Polygon area must be positive")

    hull = convex_hull(rings[0])
    hull_area = area(hull)
    if hull_area <= 0:
        raise ValueError("Convex hull area must be positive")

    boundary_length = sum(perimeter(ring) for ring in rings)
    jaggedness = max(0.0, 1 - perimeter(hull) / boundary_length)
    nonconvexity = max(0.0, 1 - actual_area / hull_area)
    return actual_area, jaggedness, nonconvexity


def score_shape(geometry: dict[str, Any]) -> ShapeComplexity:
    return score_components(
        [polygon_metrics(polygon) for polygon in polygons_of(geometry)]
    )


def score_mask(
    mask: NDArray[np.bool_], min_component_pixels: int = 4
) -> ShapeComplexity:
    if mask.ndim != 2:
        raise ValueError("Shape mask must have two dimensions")
    if min_component_pixels < 1:
        raise ValueError("Minimum component size must be positive")

    labels, _ = label(mask, structure=np.ones((3, 3), dtype=np.uint8))
    metrics = []
    for identifier, bounds in enumerate(find_objects(labels), start=1):
        if bounds is None:
            raise ValueError(f"Missing labeled component {identifier}")
        component = labels[bounds] == identifier
        component_area = int(np.count_nonzero(component))
        if component_area < min_component_pixels:
            continue
        hull = convex_hull_image(component)
        component_perimeter = perimeter_crofton(component, directions=4)
        jaggedness = max(
            0.0, 1 - perimeter_crofton(hull, directions=4) / component_perimeter
        )
        nonconvexity = 1 - component_area / np.count_nonzero(hull)
        metrics.append((component_area, jaggedness, nonconvexity))

    return score_components(metrics)
