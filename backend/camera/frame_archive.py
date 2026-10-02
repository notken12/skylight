import hashlib
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from threading import Lock

from PIL import Image

from backend.camera.camera_models import Camera, CameraSnapshot

SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class FrameArchive:
    def __init__(
        self,
        assets_dir: Path,
        fetch_snapshot: Callable[[Camera], CameraSnapshot],
    ) -> None:
        self.assets_dir = assets_dir
        self.fetch_snapshot = fetch_snapshot
        self.urls: dict[tuple[str, str], str] = {}
        self.lock = Lock()

    def fetch(self, camera: Camera) -> CameraSnapshot:
        if camera.provider_id is None:
            raise ValueError(
                f"Camera lacks provider ID: {camera.network} {camera.name}"
            )
        snapshot = self.fetch_snapshot(camera)
        with Image.open(BytesIO(snapshot.image)) as image:
            image_format = image.format
        if image_format not in SUFFIXES:
            raise ValueError(f"Unsupported camera image format: {image_format}")
        digest = hashlib.sha256(snapshot.image).hexdigest()
        frames_dir = self.assets_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        path = frames_dir / f"{digest}{SUFFIXES[image_format]}"
        with self.lock:
            if not path.exists():
                path.write_bytes(snapshot.image)
            self.urls[(camera.network, camera.provider_id)] = (
                f"/assets/frames/{path.name}"
            )
        return snapshot
