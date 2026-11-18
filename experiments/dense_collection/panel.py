import json
import random
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from backend.camera.cameras import Camera, faa_cameras
from backend.camera.faa_snapshots import (
    FAA_REFERER,
    fetch_recent_images,
    latest_image_at,
)
from backend.weather_source import fetch_bytes, fetch_faa_json
from experiments.cloud_detector.weather_features import (
    TERRAIN_COLUMN,
    load_weather_grids,
    terrain_relief_km,
)
from experiments.dense_collection.images import decode
from experiments.dense_collection.probes import DENSE_DIR, Probe, load_probes
from experiments.dense_collection.r2 import R2Store
from experiments.dense_collection.selection import sun_elevation_degrees
from experiments.encoder_comparison.embed import ENCODER_LOADERS, embed_images

PANEL_FILE = DENSE_DIR / "panel.json"
PANEL_SIZE = 200
MOUNTAIN_SHARE = 0.5
MOUNTAIN_RELIEF_KM = 1.0
RELIEF_RADIUS_CELLS = 2
PANEL_SEED = 20261118
CANDIDATE_BATCH = 32
MIN_CHECK_SUN_ELEVATION_DEGREES = 5.0
MIN_SKY_PROBABILITY = 0.5
FETCH_WORKERS = 4
DEVICE = "cpu"

type SkyCheck = Callable[[list[Camera]], list[tuple[Camera, float, str]]]


@dataclass(frozen=True)
class PanelCamera:
    camera_id: int
    name: str
    site_url: str
    latitude: float
    longitude: float
    terrain_relief_km: float | None
    group: str
    sky_probability: float
    checked_image_url: str


def camera_site(camera: Camera) -> str:
    return camera.url.split("/details/")[0]


def latest_daylit_frame(
    camera: Camera,
    at: datetime,
    fetch_json: Callable[[str], Any],
    fetch_image: Callable[[str, str], bytes],
) -> tuple[str, bytes] | None:
    assert camera.camera_id is not None
    image = latest_image_at(fetch_recent_images(camera.camera_id, fetch_json), at)
    if image is None:
        return None
    captured_at = datetime.fromisoformat(image["imageDatetime"])
    elevation = sun_elevation_degrees(captured_at, camera.latitude, camera.longitude)
    if elevation < MIN_CHECK_SUN_ELEVATION_DEGREES:
        return None
    return image["imageUri"], fetch_image(image["imageUri"], FAA_REFERER)


def sky_check(
    at: datetime,
    sky_probe: Probe,
    embed: Callable[[list], Any],
    fetch_json: Callable[[str], Any],
    fetch_image: Callable[[str, str], bytes],
) -> SkyCheck:
    def check(cameras: list[Camera]) -> list[tuple[Camera, float, str]]:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
            fetches = [
                executor.submit(
                    latest_daylit_frame, camera, at, fetch_json, fetch_image
                )
                for camera in cameras
            ]
        results = [
            (camera, fetch.result())
            for camera, fetch in zip(cameras, fetches)
            if fetch.exception() is None
        ]
        frames = [(camera, frame) for camera, frame in results if frame is not None]
        if not frames:
            return []
        probabilities = sky_probe.whole_frame_probability(
            embed([decode(frame[1]) for _, frame in frames])
        )
        return [
            (camera, round(float(probability), 4), frame[0])
            for (camera, frame), probability in zip(frames, probabilities)
        ]

    return check


def choose_cameras(
    candidates: list[Camera],
    quota: int,
    group: str,
    taken_sites: set[str],
    relief: dict[int, float | None],
    check: SkyCheck,
) -> list[PanelCamera]:
    chosen: list[PanelCamera] = []
    unchecked = [
        camera for camera in candidates if camera_site(camera) not in taken_sites
    ]
    while unchecked and len(chosen) < quota:
        batch, unchecked = unchecked[:CANDIDATE_BATCH], unchecked[CANDIDATE_BATCH:]
        for camera, probability, image_url in check(batch):
            site = camera_site(camera)
            if len(chosen) == quota or site in taken_sites:
                continue
            if probability < MIN_SKY_PROBABILITY:
                continue
            assert camera.camera_id is not None
            taken_sites.add(site)
            chosen.append(
                PanelCamera(
                    camera_id=camera.camera_id,
                    name=camera.name,
                    site_url=site,
                    latitude=camera.latitude,
                    longitude=camera.longitude,
                    terrain_relief_km=relief[camera.camera_id],
                    group=group,
                    sky_probability=probability,
                    checked_image_url=image_url,
                )
            )
        unchecked = [
            camera for camera in unchecked if camera_site(camera) not in taken_sites
        ]
    return chosen


def build_panel(
    cameras: list[Camera],
    relief: dict[int, float | None],
    check: SkyCheck,
    rng: random.Random,
) -> list[PanelCamera]:
    shuffled = sorted(cameras, key=lambda camera: camera.camera_id or 0)
    rng.shuffle(shuffled)
    mountainous = [
        camera
        for camera in shuffled
        if (relief[camera.camera_id or 0] or 0) >= MOUNTAIN_RELIEF_KM
    ]
    taken_sites: set[str] = set()
    mountain_quota = round(PANEL_SIZE * MOUNTAIN_SHARE)
    mountain = choose_cameras(
        mountainous, mountain_quota, "mountain", taken_sites, relief, check
    )
    rest = choose_cameras(
        shuffled, PANEL_SIZE - len(mountain), "random", taken_sites, relief, check
    )
    return mountain + rest


def read_panel() -> list[PanelCamera]:
    return [
        PanelCamera(**camera)
        for camera in json.loads(PANEL_FILE.read_text())["cameras"]
    ]


def main() -> None:
    at = datetime.now(UTC)
    store = R2Store.from_environment()
    probes = load_probes(store.etag, store.download)
    encoder = ENCODER_LOADERS["openclip_b32"](DEVICE)
    cameras = [
        camera
        for camera in faa_cameras(fetch_faa_json)
        if camera.feed_verified and not camera.link_only and camera.camera_id
    ]
    terrain_km = load_weather_grids(at, fetch_bytes)[TERRAIN_COLUMN]
    relief = {
        camera.camera_id or 0: terrain_relief_km(
            terrain_km, camera.latitude, camera.longitude, RELIEF_RADIUS_CELLS
        )
        for camera in cameras
    }
    check = sky_check(
        at,
        probes.sky,
        lambda images: embed_images(encoder, images, DEVICE),
        fetch_faa_json,
        fetch_bytes,
    )
    panel = build_panel(cameras, relief, check, random.Random(PANEL_SEED))
    PANEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    PANEL_FILE.write_text(
        json.dumps(
            {
                "built_at": at.isoformat(timespec="seconds"),
                "seed": PANEL_SEED,
                "mountain_relief_km": MOUNTAIN_RELIEF_KM,
                "relief_radius_cells": RELIEF_RADIUS_CELLS,
                "min_sky_probability": MIN_SKY_PROBABILITY,
                "cameras": [asdict(camera) for camera in panel],
            },
            indent=1,
        )
    )
    store.upload("panel/panel.json", PANEL_FILE)
    groups = [camera.group for camera in panel]
    print(
        f"panel: {len(panel)} cameras ({groups.count('mountain')} mountain, "
        f"{groups.count('random')} random) of {len(cameras)} FAA cameras"
    )


if __name__ == "__main__":
    main()
