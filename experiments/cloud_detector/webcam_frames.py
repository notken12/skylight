import json
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from backend.camera.camera_snapshots import CameraSnapshot, fetch_camera_snapshot
from backend.camera.cameras import Camera, load_cameras
from backend.weather_source import (
    fetch_bytes,
    fetch_faa_json,
    fetch_headers,
    fetch_json,
)
from experiments.cloud_detector.photos import EXPERIMENT_DIR, Photo

FRAMES_PER_NETWORK = {"FAA WeatherCams": 150, "ALERTWest": 150, "USGS HIVIS": 40}
EASTERNMOST_LONGITUDE = -104.0
SAMPLING_SEED = 0
LIVE_FRAME_LABEL = "live_webcam_frame"

FRAME_DIR = EXPERIMENT_DIR / "webcam_frames"
MANIFEST = EXPERIMENT_DIR / "webcam_frames.json"


def sampled_cameras(cameras: list[Camera], rng: random.Random) -> list[Camera]:
    sample = []
    for network, count in FRAMES_PER_NETWORK.items():
        eligible = [
            camera
            for camera in cameras
            if camera.network == network
            and camera.longitude <= EASTERNMOST_LONGITUDE
            and camera.feed_verified
            and not camera.link_only
        ]
        sample += rng.sample(eligible, count)
    return sample


def frame_path(index: int) -> Path:
    return FRAME_DIR / f"frame_{index:03d}.jpg"


def read_manifest() -> list[Photo]:
    return [Photo(**entry) for entry in json.loads(MANIFEST.read_text())]


def fetch_snapshots(cameras: list[Camera], at: datetime) -> list[CameraSnapshot]:
    with ThreadPoolExecutor(max_workers=8) as executor:
        fetches = [
            executor.submit(
                fetch_camera_snapshot, camera, at, fetch_faa_json, fetch_bytes
            )
            for camera in cameras
        ]
    return [fetch.result() for fetch in fetches if fetch.exception() is None]


def main() -> None:
    collected_at = datetime.now(UTC)
    cameras = sampled_cameras(
        load_cameras(fetch_json, fetch_faa_json, fetch_headers),
        random.Random(SAMPLING_SEED),
    )
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, snapshot in enumerate(fetch_snapshots(cameras, collected_at)):
        frame_path(index).write_bytes(snapshot.image)
        frames.append(
            Photo(str(frame_path(index)), LIVE_FRAME_LABEL, snapshot.image_url)
        )
    MANIFEST.write_text(json.dumps([asdict(frame) for frame in frames], indent=1))
    print(
        f"{len(frames)} of {len(cameras)} sampled cameras returned a frame "
        f"at {collected_at.isoformat()}"
    )


if __name__ == "__main__":
    main()
