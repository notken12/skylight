import json
import random
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from math import asin, degrees, radians, sin
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from backend.weather_source import fetch_bytes

GIBS_WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
LAYERS = (
    "MODIS_Terra_CorrectedReflectance_TrueColor",
    "MODIS_Aqua_CorrectedReflectance_TrueColor",
)
TILE_DEGREES = 5.0
TILE_PIXELS = 512
FIRST_DAY = date(2003, 1, 1)
LAST_DAY = date(2026, 10, 31)
MAX_ABSOLUTE_LATITUDE = 55.0
BACKGROUND_TILE_COUNT = 2000
LOCAL_TILES_PER_SCENE = 60
LOCAL_SEASON_DAYS = 30
SAMPLING_SEED = 0
JPEG_SIGNATURE = b"\xff\xd8"

EXPERIMENT_DIR = Path("output/cloud_rarity")
TILE_DIR = EXPERIMENT_DIR / "tiles"
MANIFEST = EXPERIMENT_DIR / "tiles.json"
POSITIVE_SCENES = Path(__file__).parent / "positive_scenes.json"

TileRole = Literal["background", "positive", "local"]


@dataclass(frozen=True)
class Tile:
    role: TileRole
    layer: str
    day: str
    lat: float
    lon: float

    @property
    def filename(self) -> str:
        satellite = self.layer.split("_")[1]
        return f"{self.role}_{satellite}_{self.day}_{self.lat:+06.2f}_{self.lon:+07.2f}.jpg"

    @property
    def url(self) -> str:
        half = TILE_DEGREES / 2
        bounds = (self.lat - half, self.lon - half, self.lat + half, self.lon + half)
        return f"{GIBS_WMS}?" + urlencode(
            {
                "SERVICE": "WMS",
                "REQUEST": "GetMap",
                "VERSION": "1.3.0",
                "LAYERS": self.layer,
                "CRS": "EPSG:4326",
                "BBOX": ",".join(f"{bound:.4f}" for bound in bounds),
                "WIDTH": TILE_PIXELS,
                "HEIGHT": TILE_PIXELS,
                "FORMAT": "image/jpeg",
                "TIME": self.day,
            }
        )


def background_tiles(rng: random.Random) -> list[Tile]:
    sine_limit = sin(radians(MAX_ABSOLUTE_LATITUDE))
    span_days = (LAST_DAY - FIRST_DAY).days
    return [
        Tile(
            role="background",
            layer=rng.choice(LAYERS),
            day=(FIRST_DAY + timedelta(days=rng.randrange(span_days))).isoformat(),
            lat=round(degrees(asin(rng.uniform(-sine_limit, sine_limit))), 2),
            lon=round(rng.uniform(-177.5, 177.5), 2),
        )
        for _ in range(BACKGROUND_TILE_COUNT)
    ]


def positive_tiles(scenes: list[dict]) -> list[Tile]:
    return [
        Tile("positive", layer, scene["date"], scene["lat"], scene["lon"])
        for scene in scenes
        for layer in LAYERS
    ]


def same_season_day(day: date, rng: random.Random) -> date:
    other_years = [
        year for year in range(FIRST_DAY.year, LAST_DAY.year) if year != day.year
    ]
    anchor = day.replace(year=rng.choice(other_years), day=min(day.day, 28))
    return anchor + timedelta(days=rng.randint(-LOCAL_SEASON_DAYS, LOCAL_SEASON_DAYS))


def local_tiles(scenes: list[dict], rng: random.Random) -> list[Tile]:
    locations = {(scene["lat"], scene["lon"], scene["date"]) for scene in scenes}
    return [
        Tile(
            role="local",
            layer=rng.choice(LAYERS),
            day=same_season_day(date.fromisoformat(day), rng).isoformat(),
            lat=lat,
            lon=lon,
        )
        for lat, lon, day in sorted(locations)
        for _ in range(LOCAL_TILES_PER_SCENE)
    ]


def download_available(tiles: list[Tile], fetch: Callable[[str], bytes]) -> list[Tile]:
    def is_available(tile: Tile) -> bool:
        path = TILE_DIR / tile.filename
        if path.exists():
            return True
        payload = fetch(tile.url)
        if not payload.startswith(JPEG_SIGNATURE):
            return False
        path.write_bytes(payload)
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        return [
            tile
            for tile, available in zip(tiles, executor.map(is_available, tiles))
            if available
        ]


def read_manifest() -> list[Tile]:
    return [Tile(**entry) for entry in json.loads(MANIFEST.read_text())]


def main() -> None:
    scenes = json.loads(POSITIVE_SCENES.read_text())
    rng = random.Random(SAMPLING_SEED)
    tiles = list(
        dict.fromkeys(
            background_tiles(rng) + positive_tiles(scenes) + local_tiles(scenes, rng)
        )
    )
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    available = download_available(tiles, fetch_bytes)
    MANIFEST.write_text(json.dumps([asdict(tile) for tile in available], indent=1))
    print(f"{len(available)} of {len(tiles)} requested tiles in {TILE_DIR}")


if __name__ == "__main__":
    main()
