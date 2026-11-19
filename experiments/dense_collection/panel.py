import argparse
import json
import random
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.camera.cameras import Camera, faa_cameras
from backend.weather_source import (
    fetch_bytes,
    fetch_faa_json,
    fetch_headers,
    fetch_text,
)
from experiments.cloud_detector.weather_features import (
    TERRAIN_COLUMN,
    load_weather_grids,
    terrain_relief_km,
)
from experiments.dense_collection.frame_sources import (
    FAA_PROVIDER,
    CameraSource,
    Frame,
    recent_frames,
)
from experiments.dense_collection.images import decode
from experiments.dense_collection.probes import DENSE_DIR, Probe, load_probes
from experiments.dense_collection.r2 import R2Store
from experiments.dense_collection.selection import sun_elevation_degrees
from experiments.encoder_comparison.embed import ENCODER_LOADERS, embed_images

PANEL_FILE = DENSE_DIR / "panel.json"
LENTICULAR_HOTSPOT_SITES = Path(__file__).with_name("lenticular_hotspot_sites.json")
OPEN_LICENCE_CAMERAS = Path(__file__).with_name("open_licence_cameras.json")
LENTICULAR_HOTSPOT_GROUP = "lenticular_hotspot"
FAA_ATTRIBUTION = "FAA WeatherCams (US public domain)"
PANEL_SIZE = 300
MOUNTAIN_SHARE = 0.5
MOUNTAIN_RELIEF_KM = 1.0
RELIEF_RADIUS_CELLS = 2
PANEL_SEED = 20261118
CANDIDATE_BATCH = 32
MIN_CHECK_SUN_ELEVATION_DEGREES = 5.0
MIN_SKY_PROBABILITY = 0.5
FETCH_WORKERS = 4
DEVICE = "cpu"

type SkyCheck = Callable[[list[CatalogCamera]], list[tuple[CatalogCamera, float, str]]]
type Relief = Callable[[float, float], float | None]


@dataclass(frozen=True)
class CatalogCamera(CameraSource):
    name: str
    site_url: str
    attribution: str


@dataclass(frozen=True)
class PanelCamera(CatalogCamera):
    terrain_relief_km: float | None
    group: str
    sky_probability: float
    checked_image_url: str


def faa_catalog_camera(camera: Camera) -> CatalogCamera:
    return CatalogCamera(
        provider=FAA_PROVIDER,
        camera_id=str(camera.camera_id),
        latitude=camera.latitude,
        longitude=camera.longitude,
        still_image_urls=[],
        name=camera.name,
        site_url=camera.url.split("/details/")[0],
        attribution=FAA_ATTRIBUTION,
    )


def open_licence_cameras() -> list[CatalogCamera]:
    return [
        CatalogCamera(**camera)
        for camera in json.loads(OPEN_LICENCE_CAMERAS.read_text())
    ]


def camera_key(camera: CameraSource) -> tuple[str, str]:
    return camera.provider, camera.camera_id


def latest_daylit_frame(
    camera: CatalogCamera,
    at: datetime,
    frames_of: Callable[[CameraSource], list[Frame]],
    fetch_image: Callable[[str, str | None], bytes],
) -> tuple[str, bytes] | None:
    captured = [
        (datetime.fromisoformat(frame.captured_at), frame)
        for frame in frames_of(camera)
    ]
    past = [
        (captured_at, frame) for captured_at, frame in captured if captured_at <= at
    ]
    if not past:
        return None
    captured_at, frame = max(past, key=lambda pair: pair[0])
    elevation = sun_elevation_degrees(captured_at, camera.latitude, camera.longitude)
    if elevation < MIN_CHECK_SUN_ELEVATION_DEGREES:
        return None
    return frame.image_url, fetch_image(frame.image_url, frame.referer)


def sky_check(
    at: datetime,
    sky_probe: Probe,
    embed: Callable[[list], np.ndarray],
    frames_of: Callable[[CameraSource], list[Frame]],
    fetch_image: Callable[[str, str | None], bytes],
) -> SkyCheck:
    def check(cameras: list[CatalogCamera]) -> list[tuple[CatalogCamera, float, str]]:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
            fetches = [
                executor.submit(latest_daylit_frame, camera, at, frames_of, fetch_image)
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


def panel_camera(
    camera: CatalogCamera,
    group: str,
    relief: Relief,
    sky_probability: float,
    checked_image_url: str,
) -> PanelCamera:
    return PanelCamera(
        **asdict(camera),
        terrain_relief_km=relief(camera.latitude, camera.longitude),
        group=group,
        sky_probability=sky_probability,
        checked_image_url=checked_image_url,
    )


def choose_cameras(
    candidates: list[CatalogCamera],
    quota: int,
    group: str,
    taken_sites: set[str],
    relief: Relief,
    check: SkyCheck,
) -> list[PanelCamera]:
    chosen: list[PanelCamera] = []
    unchecked = [camera for camera in candidates if camera.site_url not in taken_sites]
    while unchecked and len(chosen) < quota:
        batch, unchecked = unchecked[:CANDIDATE_BATCH], unchecked[CANDIDATE_BATCH:]
        for camera, probability, image_url in check(batch):
            if len(chosen) == quota or camera.site_url in taken_sites:
                continue
            if probability < MIN_SKY_PROBABILITY:
                continue
            taken_sites.add(camera.site_url)
            chosen.append(panel_camera(camera, group, relief, probability, image_url))
        unchecked = [
            camera for camera in unchecked if camera.site_url not in taken_sites
        ]
    return chosen


def build_panel(
    cameras: list[CatalogCamera],
    relief: Relief,
    check: SkyCheck,
    rng: random.Random,
) -> list[PanelCamera]:
    shuffled = sorted(cameras, key=lambda camera: int(camera.camera_id))
    rng.shuffle(shuffled)
    mountainous = [
        camera
        for camera in shuffled
        if (relief(camera.latitude, camera.longitude) or 0) >= MOUNTAIN_RELIEF_KM
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


def lenticular_hotspot_cameras(
    faa: list[CatalogCamera],
    open_licence: list[CatalogCamera],
    panel: list[PanelCamera],
    relief: Relief,
    check: SkyCheck,
) -> list[PanelCamera]:
    hotspot_sites = {
        site["site_url"] for site in json.loads(LENTICULAR_HOTSPOT_SITES.read_text())
    }
    in_panel = {camera_key(camera) for camera in panel}
    candidates = [
        camera
        for camera in [
            *(camera for camera in faa if camera.site_url in hotspot_sites),
            *open_licence,
        ]
        if camera_key(camera) not in in_panel
    ]
    return [
        panel_camera(camera, LENTICULAR_HOTSPOT_GROUP, relief, probability, image_url)
        for start in range(0, len(candidates), CANDIDATE_BATCH)
        for camera, probability, image_url in check(
            candidates[start : start + CANDIDATE_BATCH]
        )
        if probability >= MIN_SKY_PROBABILITY
    ]


def read_panel() -> list[PanelCamera]:
    return [
        PanelCamera(**camera)
        for camera in json.loads(PANEL_FILE.read_text())["cameras"]
    ]


def write_panel(panel: list[PanelCamera], at: datetime, store: R2Store) -> None:
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
    groups = Counter((camera.group, camera.provider) for camera in panel)
    print(f"panel: {len(panel)} cameras {dict(groups)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["build", "add_lenticular_hotspots"])
    action = parser.parse_args().action
    at = datetime.now(UTC)
    store = R2Store.from_environment()
    probes = load_probes(store.etag, store.download)
    encoder = ENCODER_LOADERS["openclip_b32"](DEVICE)
    faa = [
        faa_catalog_camera(camera)
        for camera in faa_cameras(fetch_faa_json)
        if camera.feed_verified and not camera.link_only and camera.camera_id
    ]
    terrain_km = load_weather_grids(at, fetch_bytes)[TERRAIN_COLUMN]

    def relief(latitude: float, longitude: float) -> float | None:
        return terrain_relief_km(terrain_km, latitude, longitude, RELIEF_RADIUS_CELLS)

    check = sky_check(
        at,
        probes.sky,
        lambda images: embed_images(encoder, images, DEVICE),
        lambda camera: recent_frames(camera, fetch_faa_json, fetch_headers, fetch_text),
        fetch_bytes,
    )
    if action == "build":
        write_panel(
            build_panel(faa, relief, check, random.Random(PANEL_SEED)), at, store
        )
        return
    panel = read_panel()
    added = lenticular_hotspot_cameras(
        faa, open_licence_cameras(), panel, relief, check
    )
    write_panel(panel + added, at, store)


if __name__ == "__main__":
    main()
