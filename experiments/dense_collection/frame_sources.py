from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from backend.camera.faa_snapshots import FAA_REFERER, fetch_recent_images

FAA_PROVIDER = "faa"

type FetchJson = Callable[[str], Any]
type FetchHeaders = Callable[[str], dict[str, str]]


@dataclass(frozen=True)
class CameraSource:
    provider: str
    camera_id: str
    latitude: float
    longitude: float
    still_image_urls: list[str]


@dataclass(frozen=True)
class Frame:
    key: str
    image_url: str
    filename: str
    captured_at: str
    referer: str | None


def faa_frames(camera: CameraSource, fetch_json: FetchJson) -> list[Frame]:
    return [
        Frame(
            key=image["imageUri"],
            image_url=image["imageUri"],
            filename=image["imageFilename"],
            captured_at=image["imageDatetime"],
            referer=FAA_REFERER,
        )
        for image in fetch_recent_images(int(camera.camera_id), fetch_json)
    ]


def still_frames(camera: CameraSource, fetch_headers: FetchHeaders) -> list[Frame]:
    frames = {}
    for url in camera.still_image_urls:
        modified = parsedate_to_datetime(fetch_headers(url)["last-modified"])
        captured_at = modified.astimezone(UTC)
        key = f"{camera.provider}:{camera.camera_id}@{captured_at.isoformat()}"
        frames[key] = Frame(
            key=key,
            image_url=url,
            filename=f"{captured_at:%Y%m%dT%H%M%SZ}{PurePosixPath(urlsplit(url).path).suffix}",
            captured_at=captured_at.isoformat(),
            referer=None,
        )
    return list(frames.values())


def recent_frames(
    camera: CameraSource, fetch_json: FetchJson, fetch_headers: FetchHeaders
) -> list[Frame]:
    if camera.provider == FAA_PROVIDER:
        return faa_frames(camera, fetch_json)
    return still_frames(camera, fetch_headers)
