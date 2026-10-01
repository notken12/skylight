from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates

from backend.camera.cameras import Camera
from backend.phenomena.cloud_volume import CloudVolume
from backend.phenomena.sunset.sunset_scoring import quality_grid, sunset_band

PALETTE = np.array(
    [
        (0, 100, 99, 107),
        (20, 159, 153, 125),
        (40, 247, 229, 91),
        (60, 250, 183, 65),
        (80, 231, 93, 48),
        (100, 158, 37, 63),
    ],
    dtype=np.float64,
)


@dataclass(frozen=True)
class SunsetOverlay:
    map_time: str
    forecast_time: str
    source_url: str
    band_url: str
    quality_url: str
    camera_in_band: tuple[bool, ...]
    camera_scores: tuple[int, ...]


def quality_image(scores: np.ndarray, active: np.ndarray, path: Path) -> None:
    rgb = np.stack(
        [
            np.interp(scores, PALETTE[:, 0], PALETTE[:, channel])
            for channel in (1, 2, 3)
        ],
        axis=-1,
    ).astype(np.uint8)
    alpha = np.where(active, 225, 0).astype(np.uint8)
    Image.fromarray(np.dstack((rgb, alpha)), "RGBA").save(path)


def band_image(at: datetime, path: Path) -> None:
    latitudes = np.arange(89.75, -90, -0.5)
    longitudes = np.arange(-179.75, 180, 0.5)
    latitude, longitude = np.meshgrid(latitudes, longitudes, indexing="ij")
    active = sunset_band(at, latitude, longitude)
    image = np.zeros((*active.shape, 4), dtype=np.uint8)
    image[active] = (245, 181, 65, 85)
    Image.fromarray(image, "RGBA").save(path)


def render_sunset_overlay(
    at: datetime, cloud: CloudVolume, cameras: list[Camera], output_path: Path
) -> SunsetOverlay:
    scores, latitudes, longitudes = quality_grid(cloud, at)
    latitude, longitude = np.meshgrid(latitudes, longitudes, indexing="ij")
    active = sunset_band(at, latitude, longitude)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path = output_path.with_name(f"{output_path.stem}_sunset_quality.png")
    band_path = output_path.with_name(f"{output_path.stem}_sunset_band.png")
    quality_image(scores, active, quality_path)
    band_image(at, band_path)
    camera_latitudes = np.array(
        [camera.latitude for camera in cameras], dtype=np.float64
    )
    camera_longitudes = np.array(
        [camera.longitude for camera in cameras], dtype=np.float64
    )
    camera_in_band = sunset_band(at, camera_latitudes, camera_longitudes)
    camera_scores = map_coordinates(
        scores.astype(np.float32),
        (
            (latitudes[0] - camera_latitudes) / 0.5,
            (camera_longitudes - longitudes[0]) / 0.5,
        ),
        order=1,
        mode="constant",
        cval=0,
    )
    camera_scores[~camera_in_band] = 0
    camera_scores[
        np.array([camera.link_only for camera in cameras], dtype=np.bool_)
    ] = 0
    return SunsetOverlay(
        map_time=at.isoformat(timespec="minutes"),
        forecast_time=cloud.valid_time.isoformat(timespec="minutes"),
        source_url=cloud.source_url,
        band_url=f"/assets/{band_path.name}",
        quality_url=f"/assets/{quality_path.name}",
        camera_in_band=tuple(bool(value) for value in camera_in_band),
        camera_scores=tuple(int(value) for value in np.rint(camera_scores)),
    )
