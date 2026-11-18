import json
from dataclasses import dataclass
from pathlib import Path

from experiments.cloud_detector.photos import MANIFEST as COMMONS_MANIFEST
from experiments.cloud_detector.photos import RARE_LABELS, WEBCAM_LABEL
from experiments.cloud_detector.webcam_frames import MANIFEST as LIVE_MANIFEST

COMPARISON_DIR = Path("output/encoder_comparison")
ALPINE_ORDINARY_DIR = COMPARISON_DIR / "alpine_ordinary"
RARE_WEBCAM_MANIFESTS = (
    Path("output/cloud_detector/timelapse_stills.json"),
    Path("output/cloud_detector/mined_frames.json"),
    Path("output/cloud_detector/rare_webcam_frames.json"),
)
CAMERA_OPERATORS = {
    "surveillance": "simg",
    "NERC": "nerc",
    "Brno": "brno",
    "Izana": "izana",
    "Chilbolton": "chilbolton",
    "Tapo": "tapo",
    "CBS3": "cbs3",
}


@dataclass(frozen=True)
class Frame:
    path: str
    source: str
    rare_type: str | None
    camera: str

    @property
    def is_webcam(self) -> bool:
        return self.source != "commons"


def camera_operator(camera_name: str) -> str:
    matches = [
        operator
        for marker, operator in CAMERA_OPERATORS.items()
        if marker in camera_name
    ]
    return matches[0] if matches else camera_name


def commons_frames() -> list[Frame]:
    return [
        Frame(
            path=photo["path"],
            source="webcam_sample" if photo["label"] == WEBCAM_LABEL else "commons",
            rare_type=photo["label"] if photo["label"] in RARE_LABELS else None,
            camera=photo["path"],
        )
        for photo in json.loads(COMMONS_MANIFEST.read_text())
    ]


def live_frames() -> list[Frame]:
    return [
        Frame(frame["path"], "live", None, frame["path"])
        for frame in json.loads(LIVE_MANIFEST.read_text())
    ]


def alpine_ordinary_frames() -> list[Frame]:
    return [
        Frame(str(path), "alpine", None, path.name.split("_")[0])
        for path in sorted(ALPINE_ORDINARY_DIR.glob("*.jpg"))
    ]


def rare_webcam_frames() -> list[Frame]:
    return [
        Frame(
            path=frame["path"],
            source="alpine" if manifest.name == "mined_frames.json" else "rare_webcam",
            rare_type=frame["label"],
            camera=camera_operator(frame["camera"]),
        )
        for manifest in RARE_WEBCAM_MANIFESTS
        for frame in json.loads(manifest.read_text())
    ]


def all_frames() -> list[Frame]:
    return (
        commons_frames()
        + live_frames()
        + alpine_ordinary_frames()
        + rare_webcam_frames()
    )
