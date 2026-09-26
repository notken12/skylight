from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

from aurora import AuroraEvents
from blur_filter import MIN_LAPLACIAN_VARIANCE
from sunset_overlay import SunsetOverlay
from view_scoring import ScoredCamera

VIEW_WEIGHT = 0.48
EVENT_WEIGHT = 0.32
SHARPNESS_WEIGHT = 0.2


@dataclass(frozen=True)
class RankContribution:
    view_score: float
    event_score: float
    weighted_score: float


@dataclass(frozen=True)
class CameraRank:
    score: float
    sharpness_score: float
    sharpness_contribution: float
    components: dict[str, RankContribution]


def contribution(view_score: float, event_score: float) -> RankContribution:
    return RankContribution(
        view_score=round(view_score, 1),
        event_score=round(event_score, 1),
        weighted_score=round(VIEW_WEIGHT * view_score + EVENT_WEIGHT * event_score, 1),
    )


def view_percentile(sorted_scores: list[float], score: float) -> float:
    return 100 * bisect_right(sorted_scores, score) / len(sorted_scores)


def rank_cameras(
    cameras: list[ScoredCamera],
    storms: dict[str, Any],
    sunset: SunsetOverlay,
    auroras: AuroraEvents | None,
) -> tuple[CameraRank | None, ...]:
    storm_scores = {
        feature["properties"]["id"]: feature["properties"]["interestingness"]["score"]
        for feature in storms["features"]
    }
    aurora_scores = (
        {
            feature["properties"]["id"]: feature["properties"]["interestingness"][
                "score"
            ]
            for feature in auroras.features["features"]
        }
        if auroras is not None
        else {}
    )
    accepted_storm_scores = sorted(
        camera.view_score.margin
        for camera in cameras
        if camera.view_score is not None and camera.view_score.accepted
    )
    accepted_sunset_scores = sorted(
        camera.sunset_view_score.combined_score
        for camera in cameras
        if camera.sunset_view_score is not None and camera.sunset_view_score.accepted
    )
    sharpness_values = sorted(
        camera.sharpness
        for camera in cameras
        if camera.sharpness is not None and camera.sharpness >= MIN_LAPLACIAN_VARIANCE
    )
    aurora_cameras = auroras.cameras if auroras is not None else (None for _ in cameras)

    ranks = []
    for camera, sunset_score, aurora_camera in zip(
        cameras, sunset.camera_scores, aurora_cameras, strict=True
    ):
        if camera.camera.link_only:
            ranks.append(None)
            continue
        components = {}
        if camera.view_score is not None and camera.view_score.accepted:
            components["storm"] = contribution(
                view_percentile(accepted_storm_scores, camera.view_score.margin),
                max(storm_scores[event_id] for event_id in camera.event_ids),
            )
        if camera.sunset_view_score is not None and camera.sunset_view_score.accepted:
            components["sunset"] = contribution(
                view_percentile(
                    accepted_sunset_scores, camera.sunset_view_score.combined_score
                ),
                sunset_score,
            )
        if aurora_camera is not None and aurora_camera.event_ids:
            if aurora_camera.cloud_cover_percent is None:
                raise ValueError("Aurora camera candidate is missing cloud cover")
            components["aurora"] = contribution(
                100 - aurora_camera.cloud_cover_percent,
                max(aurora_scores[event_id] for event_id in aurora_camera.event_ids),
            )
        if not components:
            ranks.append(None)
            continue
        if camera.sharpness is None:
            raise ValueError("Ranked camera is missing Laplacian sharpness")
        sharpness_score = (
            view_percentile(sharpness_values, camera.sharpness)
            if camera.sharpness >= MIN_LAPLACIAN_VARIANCE
            else 0
        )
        sharpness_contribution = round(SHARPNESS_WEIGHT * sharpness_score, 1)
        ranks.append(
            CameraRank(
                score=round(
                    sum(part.weighted_score for part in components.values())
                    + sharpness_contribution,
                    1,
                ),
                sharpness_score=round(sharpness_score, 1),
                sharpness_contribution=sharpness_contribution,
                components=components,
            )
        )
    return tuple(ranks)
