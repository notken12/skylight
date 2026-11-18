import random
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from backend.phenomena.sunset.sunset_scoring import solar_geometry

GATE_SHARE = 0.85
FAA_HISTORY_SPAN = timedelta(hours=3, minutes=15)


@dataclass(frozen=True)
class Selection:
    kind: str
    probability: float


@dataclass(frozen=True)
class AuditChoice:
    reason: str
    probability: float


def sun_elevation_degrees(at: datetime, latitude: float, longitude: float) -> float:
    return float(solar_geometry(at, np.array([latitude]), np.array([longitude]))[0][0])


def may_have_daylit_frames(at: datetime, latitude: float, longitude: float) -> bool:
    return (
        sun_elevation_degrees(at, latitude, longitude) >= 0
        or sun_elevation_degrees(at - FAA_HISTORY_SPAN, latitude, longitude) >= 0
    )


def new_daylit_images(
    images: list[dict[str, Any]],
    processed_urls: Collection[str],
    latitude: float,
    longitude: float,
) -> list[tuple[dict[str, Any], float]]:
    fresh = [image for image in images if image["imageUri"] not in processed_urls]
    with_elevation = [
        (
            image,
            sun_elevation_degrees(
                datetime.fromisoformat(image["imageDatetime"]), latitude, longitude
            ),
        )
        for image in fresh
    ]
    return sorted(
        [(image, elevation) for image, elevation in with_elevation if elevation >= 0],
        key=lambda pair: pair[0]["imageDatetime"],
    )


def label_selection(
    gate_scores: Sequence[float], budget: int, rng: random.Random
) -> list[Selection]:
    gate_count = round(budget * GATE_SHARE)
    by_score = sorted(range(len(gate_scores)), key=lambda index: -gate_scores[index])
    gate = by_score[:gate_count]
    remaining = by_score[gate_count:]
    drawn = rng.sample(remaining, min(budget - gate_count, len(remaining)))
    random_probability = len(drawn) / len(remaining) if remaining else 0.0
    selections = [Selection("", random_probability)] * len(gate_scores)
    for index in gate:
        selections[index] = Selection("gate", 1.0)
    for index in drawn:
        selections[index] = Selection("random", random_probability)
    return selections


def audit_choices(
    windows: Sequence[str],
    flagged: Collection[str],
    windows_per_pass: int,
    rng: random.Random,
) -> dict[str, AuditChoice]:
    chosen = {window: AuditChoice("flagged", 1.0) for window in flagged}
    others = [window for window in windows if window not in flagged]
    drawn = rng.sample(others, min(max(windows_per_pass - len(chosen), 0), len(others)))
    probability = len(drawn) / len(others) if others else 0.0
    return chosen | {window: AuditChoice("random", probability) for window in drawn}
