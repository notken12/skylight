from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import rankdata

from cloud_volume import CloudVolume

TILE_DEGREES = 1.5


@dataclass(frozen=True)
class CloudRegion:
    name: str
    south: float
    north: float
    west: float
    east: float


REGIONS = (
    CloudRegion("North America", 24.75, 84.75, -141.75, -51.75),
    CloudRegion("Alaska", 50.25, 72.75, -180, -141.75),
    CloudRegion("Western Aleutians", 50.25, 56.25, 171, 180),
    CloudRegion("Hawaii", 17.25, 30.75, -180, -153.75),
)


@dataclass(frozen=True)
class CloudPatch:
    region: str
    south: float
    north: float
    west: float
    east: float
    horizontal_variation: float
    vertical_variation: float
    peak_cloud_fraction: float

    @property
    def variation(self) -> float:
        return self.horizontal_variation + self.vertical_variation


@dataclass(frozen=True)
class CloudUnusualness:
    features: dict[str, Any]
    forecast_time: str
    source_url: str
    tile_degrees: float


def describe_patch(
    cloud_fraction: NDArray[np.float32],
    region: str,
    bounds: tuple[float, float, float, float],
) -> CloudPatch:
    south, north, west, east = bounds
    horizontal_variation = (
        float(np.mean(np.abs(np.diff(cloud_fraction, axis=1))))
        + float(np.mean(np.abs(np.diff(cloud_fraction, axis=2))))
    ) / 2
    vertical_variation = float(np.mean(np.abs(np.diff(cloud_fraction, axis=0))))
    return CloudPatch(
        region=region,
        south=south,
        north=north,
        west=west,
        east=east,
        horizontal_variation=horizontal_variation,
        vertical_variation=vertical_variation,
        peak_cloud_fraction=float(np.mean(np.max(cloud_fraction, axis=0))),
    )


def score_patches(patches: list[CloudPatch]) -> NDArray[np.float64]:
    variations = np.array([patch.variation for patch in patches])
    scores = np.zeros(len(patches), dtype=np.float64)
    varying = variations > 0
    if np.any(varying):
        scores[varying] = (
            100
            * (rankdata(variations[varying], method="average") - 0.5)
            / np.count_nonzero(varying)
        )
    return scores


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
            "id": f"{patch.south:.2f}:{patch.west:.2f}",
            "region": patch.region,
            "score": round(score, 1),
            "horizontal_variation": round(100 * patch.horizontal_variation, 2),
            "vertical_variation": round(100 * patch.vertical_variation, 2),
            "peak_cloud_fraction": round(100 * patch.peak_cloud_fraction, 1),
        },
    }


def classify_patches(volume: CloudVolume) -> dict[str, Any]:
    patches = []
    southward_latitudes = -volume.latitudes
    for region in REGIONS:
        for south in np.arange(region.south, region.north, TILE_DEGREES):
            north = min(south + TILE_DEGREES, region.north)
            row_start = np.searchsorted(southward_latitudes, -north, side="right")
            row_end = np.searchsorted(southward_latitudes, -south, side="right")
            for west in np.arange(region.west, region.east, TILE_DEGREES):
                east = min(west + TILE_DEGREES, region.east)
                column_start = np.searchsorted(volume.longitudes, west % 360)
                column_end = np.searchsorted(volume.longitudes, east % 360)
                if row_end - row_start < 2 or column_end - column_start < 2:
                    raise ValueError(f"ICON cloud grid does not cover {region.name} at {south}, {west}")
                patches.append(
                    describe_patch(
                        volume.cloud_fraction[
                            :, row_start:row_end, column_start:column_end
                        ],
                        region.name,
                        (float(south), float(north), float(west), float(east)),
                    )
                )
    return {
        "type": "FeatureCollection",
        "features": [
            patch_feature(patch, float(score))
            for patch, score in zip(patches, score_patches(patches), strict=True)
        ],
    }


def load_cloud_unusualness(volume: CloudVolume) -> CloudUnusualness:
    return CloudUnusualness(
        features=classify_patches(volume),
        forecast_time=volume.valid_time.isoformat(timespec="minutes"),
        source_url=volume.source_url,
        tile_degrees=TILE_DEGREES,
    )
