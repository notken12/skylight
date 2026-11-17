import argparse
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.camera.cameras import load_cameras
from backend.camera.faa_snapshots import FAA_REFERER, fetch_recent_images
from backend.weather_source import (
    fetch_bytes,
    fetch_faa_json,
    fetch_headers,
    fetch_json,
)
from experiments.cloud_detector.live_log import (
    LIVE_DIR,
    RARE_VISION_TYPES,
    append_to_log,
    read_label,
    worth_reviewing,
)
from experiments.cloud_detector.webcam_frames import fetch_snapshots

FOLLOWUP_DIR = LIVE_DIR / "followups"
ACTIVE_EVENTS = LIVE_DIR / "active_followups.json"
FOLLOWUP_LOG = LIVE_DIR / "followup_calls.csv"
MAX_FOLLOWUP_DURATION = timedelta(hours=6)
CLEAR_LOOKS_TO_END = 2
FAA_NETWORK = "FAA WeatherCams"
NOT_VISIBLE = "not_visible"


@dataclass(frozen=True)
class FollowupEvent:
    event_id: str
    network: str
    camera_name: str
    camera_id: int | None
    vision_type: str
    opened_at: str
    history_fetched: bool
    live_types: tuple[str, ...]

    def has_ended(self, now: datetime) -> bool:
        recent = self.live_types[-CLEAR_LOOKS_TO_END:]
        cleared = len(recent) == CLEAR_LOOKS_TO_END and not any(
            vision_type in RARE_VISION_TYPES for vision_type in recent
        )
        expired = now - datetime.fromisoformat(self.opened_at) > MAX_FOLLOWUP_DURATION
        return cleared or expired


@dataclass(frozen=True)
class FollowupView:
    event_id: str
    network: str
    camera_name: str
    look: str
    image_url: str
    captured_at: str
    vision_frame: str


def read_active_events() -> list[FollowupEvent]:
    if not ACTIVE_EVENTS.exists():
        return []
    return [
        FollowupEvent(**event | {"live_types": tuple(event["live_types"])})
        for event in json.loads(ACTIVE_EVENTS.read_text())
    ]


def write_active_events(events: list[FollowupEvent]) -> None:
    ACTIVE_EVENTS.write_text(json.dumps([asdict(event) for event in events], indent=1))


def open_followups(flagged_rows: list[dict[str, Any]]) -> None:
    events = read_active_events()
    followed = {(event.network, event.camera_name) for event in events}
    opened_at = datetime.now(UTC).isoformat(timespec="seconds")
    for row in flagged_rows:
        camera = (row["network"], row["camera_name"])
        if camera in followed:
            continue
        followed.add(camera)
        events.append(
            FollowupEvent(
                event_id=f"{row['run']}:{row['camera_name']}",
                network=row["network"],
                camera_name=row["camera_name"],
                camera_id=row["camera_id"],
                vision_type=row["vision_type"],
                opened_at=opened_at,
                history_fetched=False,
                live_types=(),
            )
        )
    write_active_events(events)


def collect() -> None:
    now = datetime.now(UTC)
    events = [event for event in read_active_events() if not event.has_ended(now)]
    write_active_events(events)
    if not events:
        print("NO_FOLLOWUPS: no flagged cameras are being followed")
        return

    cameras = {
        (camera.network, camera.name): camera
        for camera in load_cameras(fetch_json, fetch_faa_json, fetch_headers)
    }
    listed_events = {
        (event.network, event.camera_name): event
        for event in events
        if (event.network, event.camera_name) in cameras
    }
    looks: list[tuple[FollowupEvent, str, str, str, bytes]] = [
        (
            listed_events[(snapshot.camera.network, snapshot.camera.name)],
            "live",
            snapshot.image_url,
            snapshot.captured_at,
            snapshot.image,
        )
        for snapshot in fetch_snapshots(
            [cameras[camera] for camera in listed_events], now
        )
    ]
    for event in listed_events.values():
        if event.history_fetched or event.network != FAA_NETWORK:
            continue
        if event.camera_id is None:
            raise ValueError(f"FAA follow-up has no camera ID: {event.event_id}")
        looks += [
            (
                event,
                "history",
                image["imageUri"],
                image["imageDatetime"],
                fetch_bytes(image["imageUri"], FAA_REFERER),
            )
            for image in fetch_recent_images(event.camera_id, fetch_faa_json)
        ]
    if not looks:
        print("NO_FOLLOWUPS: no followed camera returned a frame")
        return

    run_dir = FOLLOWUP_DIR / now.strftime("%Y%m%dT%H%MZ")
    (run_dir / "labels").mkdir(parents=True)
    views = []
    for index, (event, look, image_url, captured_at, image) in enumerate(looks):
        vision_frame = f"view_{index:02d}.jpg"
        (run_dir / vision_frame).write_bytes(image)
        views.append(
            FollowupView(
                event_id=event.event_id,
                network=event.network,
                camera_name=event.camera_name,
                look=look,
                image_url=image_url,
                captured_at=captured_at,
                vision_frame=vision_frame,
            )
        )
    (run_dir / "run.json").write_text(
        json.dumps([asdict(view) for view in views], indent=1)
    )
    print(f"RUN_DIR: {run_dir.resolve()}")
    print(f"cameras followed: {len(listed_events)}, frames to label: {len(views)}")


def record(run_dir: Path, vision_model: str) -> None:
    views = json.loads((run_dir / "run.json").read_text())
    rows = []
    for view in views:
        label = read_label(run_dir, view["vision_frame"])
        rows.append(
            {
                "followup_run": run_dir.name,
                **view,
                "vision_model": vision_model,
                "vision_type": label["type"],
                "vision_confidence": label["confidence"],
                "vision_sky": label["sky"],
            }
        )
    append_to_log(FOLLOWUP_LOG, rows)

    live_types: dict[str, list[str]] = {}
    events_with_history = set()
    for row in rows:
        if row["look"] == "history":
            events_with_history.add(row["event_id"])
        elif row["vision_type"] != NOT_VISIBLE:
            live_types.setdefault(row["event_id"], []).append(row["vision_type"])
        if not worth_reviewing(row["vision_type"], row["vision_confidence"]):
            (run_dir / row["vision_frame"]).unlink()
    write_active_events(
        [
            replace(
                event,
                history_fetched=event.history_fetched
                or event.event_id in events_with_history,
                live_types=(*event.live_types, *live_types.get(event.event_id, [])),
            )
            for event in read_active_events()
        ]
    )
    still_rare = sum(row["vision_type"] in RARE_VISION_TYPES for row in rows)
    print(
        f"logged {len(rows)} follow-up frames from {run_dir.name}; "
        f"still showing a rare type: {still_rare}"
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
        collect()
        return
    record(arguments.run_dir, arguments.vision_model)


if __name__ == "__main__":
    main()
