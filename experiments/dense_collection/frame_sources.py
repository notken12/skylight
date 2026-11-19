import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from backend.camera.faa_snapshots import FAA_REFERER, fetch_recent_images

FAA_PROVIDER = "faa"
DGAC_CHILE_PROVIDER = "dgac_chile"
DGAC_CHILE_CAMERA_PAGE = "https://aipchile.dgac.gob.cl/camara/show/id/{camera_id}"
DGAC_CHILE_FRAME = re.compile(
    r'<a href="(?P<url>[^"]+\.jpg)" title="[^"]*'
    r'tomada el (?P<captured_at>\d\d-\d\d-\d{4} \d\d:\d\d:\d\d) Hora UTC"'
)

type FetchJson = Callable[[str], Any]
type FetchHeaders = Callable[[str], dict[str, str]]
type FetchText = Callable[[str], str]


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


def dgac_chile_frames(camera: CameraSource, fetch_text: FetchText) -> list[Frame]:
    page = fetch_text(DGAC_CHILE_CAMERA_PAGE.format(camera_id=camera.camera_id))
    frames = []
    for match in DGAC_CHILE_FRAME.finditer(page):
        captured_at = datetime.strptime(
            match["captured_at"], "%d-%m-%Y %H:%M:%S"
        ).replace(tzinfo=UTC)
        frames.append(
            Frame(
                key=match["url"],
                image_url=match["url"],
                filename=f"{captured_at:%Y%m%dT%H%M%SZ}.jpg",
                captured_at=captured_at.isoformat(),
                referer=None,
            )
        )
    return frames


def recent_frames(
    camera: CameraSource,
    fetch_json: FetchJson,
    fetch_headers: FetchHeaders,
    fetch_text: FetchText,
) -> list[Frame]:
    if camera.provider == FAA_PROVIDER:
        return faa_frames(camera, fetch_json)
    if camera.provider == DGAC_CHILE_PROVIDER:
        return dgac_chile_frames(camera, fetch_text)
    return still_frames(camera, fetch_headers)
