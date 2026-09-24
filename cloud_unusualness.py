from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import binary_fill_holes
from scipy.spatial import KDTree
from scipy.stats import rankdata

from scene_data import (
    CloudGrid,
    CloudPropertyGrid,
    goes_pixel_bounds,
    goes_source,
    read_goes_grid,
    read_goes_property,
)
from shape_complexity import ShapeComplexity, score_mask

type FetchText = Callable[[str], str]
type FetchBytes = Callable[[str], bytes]

SOUTH = 24.75
NORTH = 50.25
WEST = -125.25
EAST = -65.25
TILE_DEGREES = 1.5
MINIMUM_VALID_MASK_FRACTION = 0.9
MINIMUM_CLOUD_FRACTION = 0.1
NEIGHBOR_COUNT = 8
WEST_SATELLITE_EASTERN_LIMIT = -111


@dataclass(frozen=True)
class CloudProducts:
    mask: CloudGrid
    height: CloudPropertyGrid
    optical_depth: CloudPropertyGrid


@dataclass(frozen=True)
class CloudPatch:
    south: float
    north: float
    west: float
    east: float
    satellite: int
    cloud_fraction: float
    valid_fraction: float
    shape: ShapeComplexity
    alignment: float
    hole_fraction: float
    height_km: float
    height_spread_km: float
    optical_depth: float

    def features(self) -> tuple[float, ...]:
        return (
            self.cloud_fraction,
            self.shape.jaggedness,
            self.shape.nonconvexity,
            self.shape.fragmentation,
            self.alignment,
            self.hole_fraction,
            self.height_km,
            self.height_spread_km,
            float(np.log1p(self.optical_depth)),
        )


@dataclass(frozen=True)
class CloudUnusualness:
    features: dict[str, Any]
    observations: dict[str, str]
    sources: dict[str, str]
    tile_degrees: float


def require_fresh(valid_time: datetime, target_time: datetime, source: str) -> None:
    age = target_time - valid_time
    if not timedelta(0) <= age <= timedelta(minutes=15):
        raise ValueError(f"{source} observation is {age} from requested time")


def load_products(
    at: datetime, longitude: float, read_text: FetchText, read_bytes: FetchBytes
) -> CloudProducts:
    def fetch_product(product: str) -> tuple[bytes, str]:
        url = goes_source(at, longitude, read_text, product)
        return read_bytes(url), url

    with ThreadPoolExecutor(max_workers=3) as executor:
        mask_future = executor.submit(fetch_product, "ACMC")
        height_future = executor.submit(fetch_product, "ACHAC")
        optical_future = executor.submit(fetch_product, "CODC")
        mask_payload, mask_url = mask_future.result()
        height_payload, height_url = height_future.result()
        optical_payload, optical_url = optical_future.result()

    products = CloudProducts(
        mask=read_goes_grid(mask_payload, mask_url),
        height=read_goes_property(height_payload, height_url, "HT"),
        optical_depth=read_goes_property(optical_payload, optical_url, "COD"),
    )
    for product, grid in (
        ("cloud mask", products.mask),
        ("cloud height", products.height),
        ("optical depth", products.optical_depth),
    ):
        require_fresh(grid.valid_time, at, product)
    return products


def boundary_alignment(mask: NDArray[np.bool_]) -> float:
    rows, columns = np.gradient(mask.astype(np.float32))
    xx = float(np.sum(columns * columns))
    yy = float(np.sum(rows * rows))
    xy = float(np.sum(rows * columns))
    total = xx + yy
    if total == 0:
        return 0.0
    return float(np.hypot(xx - yy, 2 * xy) / total)


def property_summary(
    grid: CloudPropertyGrid, bounds: tuple[float, float, float, float]
) -> tuple[float, float] | None:
    rows, columns = goes_pixel_bounds(grid, *bounds)
    values = grid.values[rows, columns]
    valid = grid.valid[rows, columns]
    if np.count_nonzero(valid) < 4:
        return None
    observed = values[valid]
    quartiles = np.percentile(observed, [25, 50, 75])
    return float(quartiles[1]), float(quartiles[2] - quartiles[0])


def describe_patch(
    products: CloudProducts,
    bounds: tuple[float, float, float, float],
    satellite: int,
) -> CloudPatch | None:
    south, north, west, east = bounds
    rows, columns = goes_pixel_bounds(products.mask, *bounds)
    cloud_level = products.mask.cloud_level[rows, columns]
    valid = products.mask.quality[rows, columns] == 0
    valid_fraction = float(np.mean(valid))
    if valid_fraction < MINIMUM_VALID_MASK_FRACTION:
        return None
    cloud = (cloud_level >= 2) & (cloud_level <= 3) & valid
    cloud_fraction = float(np.count_nonzero(cloud) / np.count_nonzero(valid))
    if cloud_fraction < MINIMUM_CLOUD_FRACTION:
        return None
    height = property_summary(products.height, bounds)
    optical = property_summary(products.optical_depth, bounds)
    if height is None or optical is None:
        return None
    holes = binary_fill_holes(cloud) & ~cloud & valid
    return CloudPatch(
        south=south,
        north=north,
        west=west,
        east=east,
        satellite=satellite,
        cloud_fraction=cloud_fraction,
        valid_fraction=valid_fraction,
        shape=score_mask(cloud),
        alignment=boundary_alignment(cloud),
        hole_fraction=float(np.count_nonzero(holes) / np.count_nonzero(valid)),
        height_km=height[0] / 1000,
        height_spread_km=height[1] / 1000,
        optical_depth=optical[0],
    )


def score_patches(patches: list[CloudPatch]) -> NDArray[np.float64]:
    if not patches:
        return np.empty(0, dtype=np.float64)
    values = np.array([patch.features() for patch in patches], dtype=np.float64)
    ranks = np.column_stack(
        [
            rankdata(values[:, column], method="average") / (len(patches) + 1)
            for column in range(values.shape[1])
        ]
    )
    marginal_distance = np.linalg.norm(ranks - 0.5, axis=1)
    neighbor_distances, _ = KDTree(ranks).query(
        ranks, k=min(NEIGHBOR_COUNT + 1, len(patches))
    )
    neighborhood_distance = (
        neighbor_distances[:, -1]
        if neighbor_distances.ndim == 2
        else np.zeros(len(patches))
    )
    distinctiveness = marginal_distance + neighborhood_distance
    return 100 * (rankdata(distinctiveness, method="average") - 0.5) / len(patches)


def patch_feature(patch: CloudPatch, score: float) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [patch.west, patch.south],
                    [patch.east, patch.south],
                    [patch.east, patch.north],
                    [patch.west, patch.north],
                    [patch.west, patch.south],
                ]
            ],
        },
        "properties": {
            "id": f"{patch.satellite}:{patch.south:.2f}:{patch.west:.2f}",
            "score": round(score, 1),
            "satellite": patch.satellite,
            "cloud_fraction": round(100 * patch.cloud_fraction, 1),
            "valid_fraction": round(100 * patch.valid_fraction, 1),
            "shape_complexity": patch.shape.score,
            "alignment": round(patch.alignment, 3),
            "hole_fraction": round(100 * patch.hole_fraction, 1),
            "height_km": round(patch.height_km, 1),
            "height_spread_km": round(patch.height_spread_km, 1),
            "optical_depth": round(patch.optical_depth, 1),
        },
    }


def classify_patches(products_by_satellite: dict[int, CloudProducts]) -> dict[str, Any]:
    patches_by_satellite: dict[int, list[CloudPatch]] = {
        satellite: [] for satellite in products_by_satellite
    }
    for south in np.arange(SOUTH, NORTH, TILE_DEGREES):
        for west in np.arange(WEST, EAST, TILE_DEGREES):
            bounds = (
                float(south),
                float(south + TILE_DEGREES),
                float(west),
                float(west + TILE_DEGREES),
            )
            satellite = (
                18 if west + TILE_DEGREES / 2 < WEST_SATELLITE_EASTERN_LIMIT else 19
            )
            patch = describe_patch(products_by_satellite[satellite], bounds, satellite)
            if patch is not None:
                patches_by_satellite[satellite].append(patch)
    features = [
        patch_feature(patch, float(score))
        for patches in patches_by_satellite.values()
        for patch, score in zip(patches, score_patches(patches), strict=True)
    ]
    return {"type": "FeatureCollection", "features": features}


def load_cloud_unusualness(
    at: datetime, read_text: FetchText, read_bytes: FetchBytes
) -> CloudUnusualness:
    with ThreadPoolExecutor(max_workers=2) as executor:
        west_future = executor.submit(load_products, at, -120, read_text, read_bytes)
        east_future = executor.submit(load_products, at, -90, read_text, read_bytes)
        products_by_satellite = {18: west_future.result(), 19: east_future.result()}

    return CloudUnusualness(
        features=classify_patches(products_by_satellite),
        observations={
            f"GOES-{satellite}": products.mask.valid_time.isoformat(timespec="minutes")
            for satellite, products in products_by_satellite.items()
        },
        sources={
            f"GOES-{satellite} {name}": grid.source_url
            for satellite, products in products_by_satellite.items()
            for name, grid in (
                ("cloud mask", products.mask),
                ("cloud top height", products.height),
                ("optical depth", products.optical_depth),
            )
        },
        tile_degrees=TILE_DEGREES,
    )
