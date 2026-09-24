import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aurora import AuroraEvents
from cloud_unusualness import CloudUnusualness
from sunset_overlay import SunsetOverlay
from view_scoring import ScoredCamera

TEMPLATE_PATH = Path(__file__).with_name("map_template.html")


def javascript_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


def render_map(
    storms: dict[str, Any],
    cameras: list[ScoredCamera],
    sunset: SunsetOverlay,
    auroras: AuroraEvents | None,
    clouds: CloudUnusualness,
    metadata: dict[str, str],
    output_path: Path,
) -> None:
    html = TEMPLATE_PATH.read_text()
    html = html.replace("__STORMS__", javascript_json(storms))
    html = html.replace(
        "__CAMERAS__",
        javascript_json(
            [
                asdict(match.camera)
                | {
                    "event_ids": match.event_ids,
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
                }
                | {
                    "aurora_event_ids": aurora_camera.event_ids
                    if aurora_camera is not None
                    else (),
                    "aurora_cloud_cover_percent": aurora_camera.cloud_cover_percent
                    if aurora_camera is not None
                    else None,
                    "aurora_dark": aurora_camera.dark
                    if aurora_camera is not None
                    else False,
                }
                for match, in_band, sunset_score, aurora_camera in zip(
                    cameras,
                    sunset.camera_in_band,
                    sunset.camera_scores,
                    auroras.cameras if auroras is not None else (None for _ in cameras),
                    strict=True,
                )
            ]
        ),
    )
    html = html.replace(
        "__AURORAS__",
        javascript_json(
            {
                "features": auroras.features,
                "observation_time": auroras.observation_time,
                "forecast_time": auroras.forecast_time,
                "cloud_time": auroras.cloud_time,
                "cloud_source_url": auroras.cloud_source_url,
            }
            if auroras is not None
            else None
        ),
    )
    html = html.replace(
        "__SUNSET__",
        javascript_json(
            {
                "map_time": sunset.map_time,
                "forecast_time": sunset.forecast_time,
                "source_url": sunset.source_url,
                "band_url": sunset.band_url,
                "quality_url": sunset.quality_url,
            }
        ),
    )
    html = html.replace("__CLOUDS__", javascript_json(asdict(clouds)))
    html = html.replace("__METADATA__", javascript_json(metadata))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
