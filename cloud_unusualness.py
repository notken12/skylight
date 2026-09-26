from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import rankdata

from cloud_volume import CloudVolume

SOUTH = 24.75
NORTH = 50.25
WEST = -125.25
EAST = -65.25
TILE_DEGREES = 1.5


@dataclass(frozen=True)
class CloudPatch:
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
    bounds: tuple[float, float, float, float],
) -> CloudPatch:
    south, north, west, east = bounds
    horizontal_variation = (
        float(np.mean(np.abs(np.diff(cloud_fraction, axis=1))))
        + float(np.mean(np.abs(np.diff(cloud_fraction, axis=2))))
    ) / 2
    vertical_variation = float(np.mean(np.abs(np.diff(cloud_fraction, axis=0))))
    return CloudPatch(
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
            "score": round(score, 1),
            "horizontal_variation": round(100 * patch.horizontal_variation, 2),
            "vertical_variation": round(100 * patch.vertical_variation, 2),
            "peak_cloud_fraction": round(100 * patch.peak_cloud_fraction, 1),
        },
    }


def classify_patches(volume: CloudVolume) -> dict[str, Any]:
    patches = []
    for south in np.arange(SOUTH, NORTH, TILE_DEGREES):
        for west in np.arange(WEST, EAST, TILE_DEGREES):
            north = south + TILE_DEGREES
            east = west + TILE_DEGREES
            rows = np.flatnonzero(
                (volume.latitudes >= south) & (volume.latitudes < north)
            )
            columns = np.flatnonzero(
                (volume.longitudes >= west + 360) & (volume.longitudes < east + 360)
            )
            patch = describe_patch(
                volume.cloud_fraction[
                    :, rows[0] : rows[-1] + 1, columns[0] : columns[-1] + 1
                ],
                (float(south), float(north), float(west), float(east)),
            )
            patches.append(patch)
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
