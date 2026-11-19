import argparse
import json
import random
import shutil
import time
from collections import defaultdict
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from backend.camera.blur_filter import laplacian_variance
from backend.weather_source import (
    fetch_bytes,
    fetch_faa_json,
    fetch_headers,
    fetch_json,
    fetch_text,
    probsevere_source,
)
from experiments.cloud_detector.live_log import RARE_VISION_TYPES, append_to_log
from experiments.cloud_detector.weather_features import (
    icon_features,
    load_weather_grids,
    nearest_storm_features,
    probsevere_storms,
)
from experiments.dense_collection.frame_sources import (
    FetchHeaders,
    FetchJson,
    FetchText,
    Frame,
    recent_frames,
)
from experiments.dense_collection.images import (
    contact_sheet,
    decode,
    mean_brightness,
    rolling_jpeg,
)
from experiments.dense_collection.labels import (
    LABEL_KEYS,
    is_valid_label,
    label_path,
    read_label,
)
from experiments.dense_collection.panel import PANEL_FILE, PanelCamera, read_panel
from experiments.dense_collection.probes import DENSE_DIR, Probe, load_probes
from experiments.dense_collection.r2 import R2Store, TarShardWriter
from experiments.dense_collection.selection import (
    audit_choices,
    label_selection,
    may_have_daylit_frames,
    new_daylit_frames,
)
from experiments.encoder_comparison.embed import ENCODER_LOADERS, embed_images

PASSES_DIR = DENSE_DIR / "passes"
PROCESSED_URLS = DENSE_DIR / "processed_urls.tsv"
LABELS_DIR = DENSE_DIR / "labels"
AUDIT_LOG = DENSE_DIR / "audit_windows.csv"
CRON_LOG = DENSE_DIR / "cron.log"
DAILY_LABEL_BUDGET = 900
PASSES_PER_DAY = 8
LABELS_PER_PASS = DAILY_LABEL_BUDGET // PASSES_PER_DAY
AUDIT_WINDOWS_PER_PASS = 5
PROCESSED_URL_RETENTION = timedelta(days=1)
ROLLING_SHARD_BYTES = 200_000_000
LABELLED_SHARD_BYTES = 2_000_000_000
FETCH_WORKERS = 4
DEVICE = "cpu"

type Embed = Callable[[list], np.ndarray]


@dataclass(frozen=True)
class FetchedFrame:
    frame: Frame
    sun_elevation_degrees: float
    path: Path


def read_processed_urls(at: datetime) -> dict[str, str]:
    if not PROCESSED_URLS.exists():
        return {}
    entries = dict(
        line.split("\t")[::-1] for line in PROCESSED_URLS.read_text().splitlines()
    )
    return recent_processed_urls(entries, at)


def recent_processed_urls(entries: dict[str, str], at: datetime) -> dict[str, str]:
    cutoff = at - PROCESSED_URL_RETENTION
    return {
        url: captured_at
        for url, captured_at in entries.items()
        if datetime.fromisoformat(captured_at) >= cutoff
    }


def write_processed_urls(entries: dict[str, str]) -> None:
    PROCESSED_URLS.write_text(
        "".join(f"{captured_at}\t{url}\n" for url, captured_at in entries.items())
    )


def frame_file(frames_dir: Path, camera_id: str, image_filename: str) -> Path:
    return frames_dir / f"{camera_id}_{image_filename}"


def fetch_camera_frames(
    camera: PanelCamera,
    processed_keys: Collection[str],
    frames_dir: Path,
    fetch_json: FetchJson,
    fetch_headers: FetchHeaders,
    fetch_text: FetchText,
    fetch_image: Callable[[str, str | None], bytes],
) -> list[FetchedFrame]:
    wanted = new_daylit_frames(
        recent_frames(camera, fetch_json, fetch_headers, fetch_text),
        processed_keys,
        camera.latitude,
        camera.longitude,
    )
    fetched = []
    for frame, elevation in wanted:
        path = frame_file(frames_dir, camera.camera_id, frame.filename)
        path.write_bytes(fetch_image(frame.image_url, frame.referer))
        fetched.append(FetchedFrame(frame, round(elevation, 2), path))
    return fetched


def camera_rows(
    pass_id: str,
    camera: PanelCamera,
    frames: list[FetchedFrame],
    embeddings: np.ndarray,
    gate_probe: Probe,
    weather: dict[str, Any],
    first_embedding_row: int,
) -> list[dict[str, Any]]:
    gate_scores = gate_probe.max_view_probability(embeddings)
    return [
        {
            "pass_id": pass_id,
            "provider": camera.provider,
            "camera_id": camera.camera_id,
            "camera_name": camera.name,
            "panel_group": camera.group,
            "latitude": camera.latitude,
            "longitude": camera.longitude,
            "terrain_relief_km": camera.terrain_relief_km,
            "frame_key": frame.frame.key,
            "image_url": frame.frame.image_url,
            "image_filename": frame.frame.filename,
            "captured_at": frame.frame.captured_at,
            "sun_elevation_degrees": frame.sun_elevation_degrees,
            "gate_score": round(float(gate_score), 5),
            "embedding_archive": f"embeddings/{pass_id}.npz",
            "embedding_row": first_embedding_row + index,
            **weather,
        }
        for index, (frame, gate_score) in enumerate(zip(frames, gate_scores))
    ]


class StageClock:
    def __init__(self) -> None:
        self.seconds: defaultdict[str, float] = defaultdict(float)
        self.started = time.monotonic()

    def lap(self, stage: str) -> None:
        now = time.monotonic()
        self.seconds[stage] += now - self.started
        self.started = now

    def summary(self) -> str:
        return " ".join(
            f"{stage}={seconds / 60:.1f}min" for stage, seconds in self.seconds.items()
        )


def collect(at: datetime, rng: random.Random) -> None:
    clock = StageClock()
    pass_id = at.strftime("%Y%m%dT%H%MZ")
    candidates = [
        camera
        for camera in read_panel()
        if may_have_daylit_frames(at, camera.latitude, camera.longitude)
    ]
    if not candidates:
        print("NO_FRAMES: no panel camera has had daylight in the last 3 hours")
        return
    store = R2Store.from_environment()
    gate_probe = load_probes(store.etag, store.download).gate
    encoder = ENCODER_LOADERS["openclip_b32"](DEVICE)
    weather_grids = load_weather_grids(at, fetch_bytes)
    storms = probsevere_storms(fetch_json(probsevere_source(None, fetch_text)))
    processed_urls = read_processed_urls(at)
    pass_dir = PASSES_DIR / pass_id
    frames_dir = pass_dir / "frames"
    frames_dir.mkdir(parents=True)
    rolling = TarShardWriter(
        pass_dir, f"rolling/{pass_id}", store.upload, ROLLING_SHARD_BYTES
    )
    clock.lap("setup")

    rows: list[dict[str, Any]] = []
    embeddings: list[np.ndarray] = []
    failed_cameras = 0
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        fetches = [
            executor.submit(
                fetch_camera_frames,
                camera,
                processed_urls,
                frames_dir,
                fetch_faa_json,
                fetch_headers,
                fetch_text,
                fetch_bytes,
            )
            for camera in candidates
        ]
        for camera, fetch in zip(candidates, fetches):
            if fetch.exception() is not None:
                failed_cameras += 1
                continue
            frames = fetch.result()
            clock.lap("fetch_wait")
            if not frames:
                continue
            payloads = [frame.path.read_bytes() for frame in frames]
            images = [decode(payload) for payload in payloads]
            camera_embeddings = embed_images(encoder, images, DEVICE)
            clock.lap("embed")
            new_rows = camera_rows(
                pass_id,
                camera,
                frames,
                camera_embeddings,
                gate_probe,
                icon_features(weather_grids, camera.latitude, camera.longitude)
                | nearest_storm_features(storms, camera.latitude, camera.longitude),
                len(rows),
            )
            for row, payload, image in zip(new_rows, payloads, images):
                member = f"{camera.camera_id}/{row['image_filename']}"
                row["sharpness"] = round(laplacian_variance(payload), 1)
                row["brightness"] = mean_brightness(image)
                row["rolling_archive"] = rolling.add(member, rolling_jpeg(image))
                row["rolling_member"] = member
            rows += new_rows
            embeddings.append(camera_embeddings.astype(np.float16))
            clock.lap("measure_and_roll")
    if not rows:
        shutil.rmtree(pass_dir)
        print(
            f"NO_FRAMES: {len(candidates)} cameras had no new daylit frames "
            f"({failed_cameras} failed)"
        )
        return
    rolling.close()
    embedding_file = pass_dir / "embeddings.npz"
    np.savez(
        embedding_file,
        embeddings=np.concatenate(embeddings),
        image_urls=np.array([row["image_url"] for row in rows]),
    )
    store.upload(f"embeddings/{pass_id}.npz", embedding_file)
    embedding_file.unlink()
    write_processed_urls(
        processed_urls | {row["frame_key"]: row["captured_at"] for row in rows}
    )
    clock.lap("upload")

    selections = label_selection(
        [row["gate_score"] for row in rows], LABELS_PER_PASS, rng
    )
    selected = [index for index, selection in enumerate(selections) if selection.kind]
    rng.shuffle(selected)
    view_names = {
        index: f"view_{position:03d}.jpg" for position, index in enumerate(selected)
    }
    (pass_dir / "labels").mkdir()
    for index, row in enumerate(rows):
        row["selection"] = selections[index].kind
        row["selection_probability"] = round(selections[index].probability, 6)
        row["view_name"] = view_names.get(index, "")
        if index in view_names:
            (pass_dir / view_names[index]).hardlink_to(
                frame_file(frames_dir, row["camera_id"], row["image_filename"])
            )
    (pass_dir / "pass.json").write_text(
        json.dumps({"pass_id": pass_id, "started_at": at.isoformat(), "frames": rows})
    )
    clock.lap("select")
    print(f"RUN_DIR: {pass_dir.resolve()}")
    print(
        f"cameras: {len(candidates)} checked, {failed_cameras} failed; "
        f"frames: {len(rows)} embedded, {len(selected)} to label; "
        f"uploaded: {dict(store.uploaded_bytes)}; {clock.summary()}"
    )


def labelled_rows(
    pass_dir: Path, rows: list[dict[str, Any]], vision_model: str
) -> list[dict[str, Any]]:
    labelled = []
    for row in rows:
        label = dict.fromkeys(LABEL_KEYS, "")
        if row["view_name"]:
            label = read_label(label_path(pass_dir, row["view_name"]))
            if not is_valid_label(label):
                raise ValueError(f"Invalid or missing label for {row['view_name']}")
        labelled.append(
            row
            | {"vision_model": vision_model if row["view_name"] else ""}
            | {f"label_{key}": label[key] for key in LABEL_KEYS}
        )
    return labelled


def write_audit_sheets(
    pass_dir: Path,
    pass_id: str,
    rows: list[dict[str, Any]],
    store: R2Store,
    rng: random.Random,
) -> list[dict[str, Any]]:
    windows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        windows.setdefault(str(row["camera_id"]), []).append(row)
    flagged = {
        camera_id
        for camera_id, window in windows.items()
        if any(row["label_type"] in RARE_VISION_TYPES for row in window)
    }
    day = f"{pass_id[:4]}-{pass_id[4:6]}-{pass_id[6:8]}"
    audit_rows = []
    for camera_id, choice in audit_choices(
        list(windows), flagged, AUDIT_WINDOWS_PER_PASS, rng
    ).items():
        window = sorted(windows[camera_id], key=lambda row: row["captured_at"])
        key = f"audit/{day}/{pass_id}_{camera_id}"
        sheet = pass_dir / f"audit_{camera_id}.jpg"
        manifest = pass_dir / f"audit_{camera_id}.json"
        sheet.write_bytes(
            contact_sheet(
                [
                    decode(
                        frame_file(
                            pass_dir / "frames", row["camera_id"], row["image_filename"]
                        ).read_bytes()
                    )
                    for row in window
                ],
                [
                    f"{index}  {row['captured_at'][11:16]}Z"
                    for index, row in enumerate(window)
                ],
            )
        )
        manifest.write_text(
            json.dumps(
                {
                    "pass_id": pass_id,
                    "camera_id": camera_id,
                    "camera_name": window[0]["camera_name"],
                    "reason": choice.reason,
                    "sampling_probability": choice.probability,
                    "frames": [
                        {
                            "index": index,
                            "captured_at": row["captured_at"],
                            "image_url": row["image_url"],
                            "rolling_archive": row["rolling_archive"],
                            "rolling_member": row["rolling_member"],
                            "label_type": row["label_type"],
                        }
                        for index, row in enumerate(window)
                    ],
                },
                indent=1,
            )
        )
        store.upload(f"{key}.jpg", sheet)
        store.upload(f"{key}.json", manifest)
        audit_rows.append(
            {
                "pass_id": pass_id,
                "camera_id": camera_id,
                "camera_name": window[0]["camera_name"],
                "reason": choice.reason,
                "sampling_probability": round(choice.probability, 6),
                "frames": len(window),
                "sheet": f"{key}.jpg",
            }
        )
    return audit_rows


def record(pass_dir: Path, vision_model: str) -> None:
    saved = json.loads((pass_dir / "pass.json").read_text())
    pass_id = saved["pass_id"]
    store = R2Store.from_environment()
    rows = labelled_rows(pass_dir, saved["frames"], vision_model)

    labelled = TarShardWriter(
        pass_dir, f"labelled/{pass_id}", store.upload, LABELLED_SHARD_BYTES
    )
    for row in rows:
        if not row["view_name"]:
            row["labelled_archive"] = row["labelled_member"] = ""
            continue
        member = f"{row['camera_id']}/{row['image_filename']}"
        row["labelled_archive"] = labelled.add(
            member, (pass_dir / row["view_name"]).read_bytes()
        )
        row["labelled_member"] = member
    labelled.close()

    audit_rows = write_audit_sheets(
        pass_dir, pass_id, rows, store, random.Random(f"{pass_id} audit")
    )
    day = f"{pass_id[:4]}-{pass_id[4:6]}-{pass_id[6:8]}"
    frame_log = DENSE_DIR / f"frames_{day}.csv"
    append_to_log(frame_log, rows)
    if audit_rows:
        append_to_log(AUDIT_LOG, audit_rows)
    LABELS_DIR.mkdir(exist_ok=True)
    labels_file = LABELS_DIR / f"{pass_id}.json"
    labels_file.write_text(
        json.dumps(
            {
                row["view_name"]: {
                    "image_url": row["image_url"],
                    **{key: row[f"label_{key}"] for key in LABEL_KEYS},
                }
                for row in rows
                if row["view_name"]
            },
            indent=1,
        )
    )
    store.upload(f"logs/labels/{pass_id}.json", labels_file)
    store.upload(f"logs/{frame_log.name}", frame_log)
    if AUDIT_LOG.exists():
        store.upload(f"logs/{AUDIT_LOG.name}", AUDIT_LOG)
    if CRON_LOG.exists():
        store.upload(f"logs/{CRON_LOG.name}", CRON_LOG)
    store.upload("panel/panel.json", PANEL_FILE)
    shutil.rmtree(pass_dir)

    rare = [row for row in rows if row["label_type"] in RARE_VISION_TYPES]
    print(
        f"logged {len(rows)} frames from {pass_id}; labelled: "
        f"{sum(bool(row['view_name']) for row in rows)}; rare calls: {len(rare)}; "
        f"audit sheets: {len(audit_rows)}; uploaded: {dict(store.uploaded_bytes)}"
    )
    for row in rare:
        print(
            f"  {row['label_type']} ({row['label_confidence']}) {row['camera_name']} "
            f"{row['captured_at']} -> {row['labelled_archive']}:{row['labelled_member']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect")
    record_command = commands.add_parser("record")
    record_command.add_argument("pass_dir", type=Path)
    record_command.add_argument("vision_model")
    arguments = parser.parse_args()
    if arguments.command == "collect":
        at = datetime.now(UTC)
        collect(at, random.Random(at.strftime("%Y%m%dT%H%MZ")))
        return
    record(arguments.pass_dir, arguments.vision_model)


if __name__ == "__main__":
    main()
