import argparse
import csv
import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.camera.cameras import Camera, load_cameras
from backend.phenomena.sunset.sunset_scoring import solar_geometry
from backend.weather_source import fetch_faa_json, fetch_headers, fetch_json
from experiments.cloud_detector.photos import Photo
from experiments.cloud_detector.webcam_frames import (
    FRAMES_PER_NETWORK,
    LIVE_FRAME_LABEL,
    fetch_snapshots,
)
from experiments.cloud_detector.zero_shot import zero_shot_scores

LIVE_DIR = Path("output/cloud_live")
CALL_LOG = LIVE_DIR / "detector_calls.csv"
CAMERAS_PER_RUN = 300
MIN_DAYLIGHT_CAMERAS = 50
MIN_SUN_ELEVATION_DEGREES = 3.0
HIGHEST_SCORING_FOR_VISION = 20
RANDOM_FOR_VISION = 20
RARE_VISION_TYPES = frozenset(
    {
        "mammatus",
        "lenticular",
        "asperitas",
        "kelvin_helmholtz",
        "shelf_cloud",
        "roll_cloud",
        "noctilucent",
    }
)


@dataclass(frozen=True)
class LiveFrame:
    network: str
    camera_name: str
    camera_url: str
    latitude: float
    longitude: float
    image_url: str
    captured_at: str
    rare_probability: float
    predicted_type: str
    vision_frame: str | None
    vision_selection: str | None


def daylight_cameras(cameras: list[Camera], at: datetime) -> list[Camera]:
    sampled_networks = [
        camera
        for camera in cameras
        if camera.network in FRAMES_PER_NETWORK
        and camera.feed_verified
        and not camera.link_only
    ]
    sun_elevations = solar_geometry(
        at,
        np.array([camera.latitude for camera in sampled_networks]),
        np.array([camera.longitude for camera in sampled_networks]),
    )[0]
    return [
        camera
        for camera, elevation in zip(sampled_networks, sun_elevations)
        if elevation >= MIN_SUN_ELEVATION_DEGREES
    ]


def collect(rng: random.Random) -> None:
    at = datetime.now(UTC)
    eligible = daylight_cameras(
        load_cameras(fetch_json, fetch_faa_json, fetch_headers), at
    )
    if len(eligible) < MIN_DAYLIGHT_CAMERAS:
        print(f"NO_RUN: only {len(eligible)} cameras are in daylight")
        return
    snapshots = fetch_snapshots(
        rng.sample(eligible, min(CAMERAS_PER_RUN, len(eligible))), at
    )
    run_dir = LIVE_DIR / at.strftime("%Y%m%dT%H%MZ")
    (run_dir / "labels").mkdir(parents=True)
    all_frames = [run_dir / f"all_{index:03d}.jpg" for index in range(len(snapshots))]
    for path, snapshot in zip(all_frames, snapshots):
        path.write_bytes(snapshot.image)
    scores = zero_shot_scores(
        [
            Photo(str(path), LIVE_FRAME_LABEL, snapshot.image_url)
            for path, snapshot in zip(all_frames, snapshots)
        ]
    )

    by_score = sorted(
        range(len(snapshots)), key=lambda index: -scores[index].rare_probability
    )
    selection = dict.fromkeys(by_score[:HIGHEST_SCORING_FOR_VISION], "highest_score")
    remaining = by_score[HIGHEST_SCORING_FOR_VISION:]
    selection |= dict.fromkeys(
        rng.sample(remaining, min(RANDOM_FOR_VISION, len(remaining))), "random"
    )
    vision_order = list(selection)
    rng.shuffle(vision_order)
    vision_names = {
        index: f"view_{position:02d}.jpg" for position, index in enumerate(vision_order)
    }
    for index, path in enumerate(all_frames):
        if index in vision_names:
            path.rename(run_dir / vision_names[index])
        else:
            path.unlink()

    frames = [
        LiveFrame(
            network=snapshot.camera.network,
            camera_name=snapshot.camera.name,
            camera_url=snapshot.camera.url,
            latitude=snapshot.camera.latitude,
            longitude=snapshot.camera.longitude,
            image_url=snapshot.image_url,
            captured_at=snapshot.captured_at,
            rare_probability=round(score.rare_probability, 4),
            predicted_type=score.predicted_type,
            vision_frame=vision_names.get(index),
            vision_selection=selection.get(index),
        )
        for index, (snapshot, score) in enumerate(zip(snapshots, scores))
    ]
    (run_dir / "run.json").write_text(
        json.dumps([asdict(frame) for frame in frames], indent=1)
    )
    print(f"RUN_DIR: {run_dir.resolve()}")
    print(f"frames scored: {len(frames)}, frames to label: {len(vision_names)}")


def record(run_dir: Path, vision_model: str) -> None:
    frames = json.loads((run_dir / "run.json").read_text())
    rows = []
    for frame in frames:
        label = {"type": "", "confidence": "", "sky": ""}
        if frame["vision_frame"] is not None:
            label_path = (
                run_dir / "labels" / Path(frame["vision_frame"]).with_suffix(".json")
            )
            label = json.loads(label_path.read_text())
        rows.append(
            {
                "run": run_dir.name,
                **frame,
                "vision_model": vision_model if frame["vision_frame"] else "",
                "vision_type": label["type"],
                "vision_confidence": label["confidence"],
                "vision_sky": label["sky"],
            }
        )
    is_new_log = not CALL_LOG.exists()
    with CALL_LOG.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        if is_new_log:
            writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        worth_reviewing = (
            row["vision_type"] in RARE_VISION_TYPES or row["vision_confidence"] == "low"
        )
        if row["vision_frame"] is not None and not worth_reviewing:
            (run_dir / row["vision_frame"]).unlink()
    flagged = [row for row in rows if row["vision_type"] in RARE_VISION_TYPES]
    print(f"logged {len(rows)} frames from {run_dir.name}; flagged: {len(flagged)}")
    for row in flagged:
        print(
            f"  {row['vision_type']} ({row['vision_confidence']}) "
            f"{row['camera_name']} -> {run_dir / row['vision_frame']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect")
    record_command = commands.add_parser("record")
    record_command.add_argument("run_dir", type=Path)
    record_command.add_argument("vision_model")
    arguments = parser.parse_args()
    if arguments.command == "collect":
        collect(random.Random())
        return
    record(arguments.run_dir, arguments.vision_model)


if __name__ == "__main__":
    main()
