import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from backend.weather_source import fetch_bytes, fetch_json

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
RARE_CATEGORIES = {
    "mammatus": "Mammatus clouds",
    "lenticular": "Lenticular clouds",
    "asperitas": "Asperitas clouds",
    "kelvin_helmholtz": "Fluctus clouds",
    "shelf_cloud": "Shelf clouds",
    "roll_cloud": "Volutus",
    "noctilucent": "Noctilucent clouds",
}
ORDINARY_CATEGORIES = {
    "cumulus_humilis": "Cumulus humilis clouds",
    "cumulus_mediocris": "Cumulus mediocris clouds",
    "cumulus_congestus": "Cumulus congestus clouds",
    "stratocumulus": "Stratocumulus clouds",
    "altocumulus": "Altocumulus clouds",
    "altostratus": "Altostratus clouds",
    "cirrus": "Cirrus clouds",
    "stratus": "Stratus clouds",
    "nimbostratus": "Nimbostratus clouds",
    "overcast": "Overcast",
}
RARE_LABELS = tuple(RARE_CATEGORIES)
WEBCAM_LABEL = "webcam_frame"
WEBCAM_SAMPLE_DIRS = (
    Path("data/camera_view_samples"),
    Path("data/sunset_view_samples"),
)
PHOTOS_PER_RARE_LABEL = 40
PHOTOS_PER_ORDINARY_LABEL = 25
CATEGORY_PAGE_SIZE = 50
THUMBNAIL_WIDTH = 500
SECONDS_BETWEEN_REQUESTS = 1.0

EXPERIMENT_DIR = Path("output/cloud_detector")
PHOTO_DIR = EXPERIMENT_DIR / "photos"
MANIFEST = EXPERIMENT_DIR / "photos.json"


@dataclass(frozen=True)
class Photo:
    path: str
    label: str
    source_url: str


def category_listing_url(category: str) -> str:
    return f"{COMMONS_API}?" + urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "categorymembers",
            "gcmtitle": f"Category:{category}",
            "gcmtype": "file",
            "gcmlimit": CATEGORY_PAGE_SIZE,
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": THUMBNAIL_WIDTH,
        }
    )


def category_photos(
    label: str,
    category: str,
    limit: int,
    fetch_listing: Callable[[str], Any],
    fetch_image: Callable[[str], bytes],
) -> list[Photo]:
    pages = fetch_listing(category_listing_url(category))["query"]["pages"]
    jpeg_files = sorted(
        (page["pageid"], page["imageinfo"][0])
        for page in pages.values()
        if page["imageinfo"][0]["mime"] == "image/jpeg"
    )[:limit]
    photos = []
    for page_id, file in jpeg_files:
        path = PHOTO_DIR / f"{label}_{page_id}.jpg"
        if not path.exists():
            time.sleep(SECONDS_BETWEEN_REQUESTS)
            path.write_bytes(fetch_image(file["thumburl"]))
        photos.append(Photo(str(path), label, file["descriptionurl"]))
    return photos


def webcam_photos() -> list[Photo]:
    return [
        Photo(str(directory / sample["filename"]), WEBCAM_LABEL, sample["image_url"])
        for directory in WEBCAM_SAMPLE_DIRS
        for sample in json.loads((directory / "manifest.json").read_text())["samples"]
    ]


def read_manifest() -> list[Photo]:
    return [Photo(**entry) for entry in json.loads(MANIFEST.read_text())]


def main() -> None:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    limits = dict.fromkeys(RARE_CATEGORIES, PHOTOS_PER_RARE_LABEL) | dict.fromkeys(
        ORDINARY_CATEGORIES, PHOTOS_PER_ORDINARY_LABEL
    )
    photos = webcam_photos()
    for label, category in (RARE_CATEGORIES | ORDINARY_CATEGORIES).items():
        time.sleep(SECONDS_BETWEEN_REQUESTS)
        photos += category_photos(
            label, category, limits[label], fetch_json, fetch_bytes
        )
        print(f"{label}: {sum(photo.label == label for photo in photos)} photos")
    MANIFEST.write_text(json.dumps([asdict(photo) for photo in photos], indent=1))
    print(f"{len(photos)} photos listed in {MANIFEST}")


if __name__ == "__main__":
    main()
