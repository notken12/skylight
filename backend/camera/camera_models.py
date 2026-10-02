from dataclasses import dataclass


@dataclass(frozen=True)
class Camera:
    network: str
    name: str
    latitude: float
    longitude: float
    url: str
    direction: str | None = None
    view_time: str | None = None
    azimuth_degrees: float | None = None
    bearing_tolerance_degrees: float | None = None
    camera_id: int | None = None
    snapshot_url: str | None = None
    operated_by: str | None = None
    sky_facing: bool = False
    night_sky_capable: bool = False
    link_only: bool = False
    feed_verified: bool = True
    provider_id: str | None = None


@dataclass(frozen=True)
class CameraSnapshot:
    camera: Camera
    image: bytes
    captured_at: str | None
    image_url: str


@dataclass(frozen=True)
class CameraFrame:
    image_url: str
    captured_at: str | None
