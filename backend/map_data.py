from dataclasses import asdict
from typing import Any

from backend.camera.camera_ranking import rank_cameras
from backend.camera.view_scoring import ScoredCamera
from backend.phenomena.aurora.aurora import AuroraEvents
from backend.phenomena.cloud_unusualness import CloudUnusualness
from backend.phenomena.sunset.sunset_overlay import SunsetOverlay


def build_map_data(
    storms: dict[str, Any],
    cameras: list[ScoredCamera],
    sunset: SunsetOverlay,
    auroras: AuroraEvents | None,
    clouds: CloudUnusualness,
    metadata: dict[str, str],
) -> dict[str, Any]:
    ranks = rank_cameras(cameras, storms, sunset, auroras)
    camera_rows = [
        asdict(match.camera)
        | {
            "event_ids": match.event_ids,
            "rank": asdict(rank) if rank is not None else None,
            "sunset_band": in_band,
            "sunset_score": sunset_score,
            "frame": asdict(match.frame) if match.frame is not None else None,
            "sharpness": match.sharpness,
            "image_scores": asdict(match.image_scores)
            if match.image_scores is not None
            else None,
            "view_score": asdict(match.view_score)
            if match.view_score is not None
            else None,
            "sunset_view_score": asdict(match.sunset_view_score)
            if match.sunset_view_score is not None
            else None,
            "aurora_event_ids": aurora_camera.event_ids
            if aurora_camera is not None
            else (),
            "aurora_cloud_cover_percent": aurora_camera.cloud_cover_percent
            if aurora_camera is not None
            else None,
            "aurora_dark": aurora_camera.dark if aurora_camera is not None else False,
        }
        for match, rank, in_band, sunset_score, aurora_camera in zip(
            cameras,
            ranks,
            sunset.camera_in_band,
            sunset.camera_scores,
            auroras.cameras if auroras is not None else (None for _ in cameras),
            strict=True,
        )
    ]
    return {
        "storms": storms,
        "cameras": camera_rows,
        "sunset": asdict(sunset),
        "auroras": asdict(auroras) if auroras is not None else None,
        "clouds": asdict(clouds),
        "metadata": metadata,
    }
