from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cameras import Camera
from faa_snapshots import FAA_REFERER, fetch_latest_image

type FetchJson = Callable[[str], Any]
type FetchBytes = Callable[[str, str | None], bytes]


@dataclass(frozen=True)
class CameraSnapshot:
    camera: Camera
    image: bytes
    captured_at: str
    image_url: str


@dataclass(frozen=True)
class CameraFrame:
    image_url: str
    captured_at: str


def latest_camera_frame(
    camera: Camera, at: datetime, fetch_faa_json: FetchJson
) -> CameraFrame:
    if camera.network == "FAA WeatherCams":
        if camera.camera_id is None:
            raise ValueError("FAA camera ID is required for snapshot retrieval")
        image = fetch_latest_image(camera.camera_id, at, fetch_faa_json)
        return CameraFrame(image["imageUri"], image["imageDatetime"])

    if camera.snapshot_url is not None and camera.view_time is not None:
        return CameraFrame(camera.snapshot_url, camera.view_time)

    if camera.network == "Iowa Mesonet" and camera.view_time is not None:
        return CameraFrame(camera.url, camera.view_time)

    raise ValueError(f"No snapshot source for {camera.network}")


def fetch_camera_snapshot(
    camera: Camera,
    at: datetime,
    fetch_faa_json: FetchJson,
    fetch_bytes: FetchBytes,
) -> CameraSnapshot:
    frame = latest_camera_frame(camera, at, fetch_faa_json)
    referer = FAA_REFERER if camera.network == "FAA WeatherCams" else None
    return CameraSnapshot(
        camera=camera,
        image=fetch_bytes(frame.image_url, referer),
        captured_at=frame.captured_at,
        image_url=frame.image_url,
    )
