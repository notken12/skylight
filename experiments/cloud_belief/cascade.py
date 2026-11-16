import csv
import json
from dataclasses import dataclass

import numpy as np

from experiments.cloud_belief.belief_filter import (
    ObservationModel,
    SkyObservation,
    observation_model_from_counts,
)
from experiments.cloud_detector.photos import EXPERIMENT_DIR, RARE_LABELS
from experiments.cloud_detector.zero_shot import SCORES_CSV

VISION_MODEL_LABELS = EXPERIMENT_DIR / "vision_model_labels.json"


@dataclass(frozen=True)
class ScreenedPhoto:
    shows_rare_cloud: bool
    screen_score: float
    vision_observation: SkyObservation


def vision_observation(cloud_type: str, confidence: str) -> SkyObservation:
    if cloud_type == "none":
        return (
            SkyObservation.CONFIDENT_NONE
            if confidence == "high"
            else SkyObservation.UNSURE_NONE
        )
    return (
        SkyObservation.CONFIDENT_RARE
        if confidence == "high"
        else SkyObservation.UNSURE_RARE
    )


def read_screened_photos() -> list[ScreenedPhoto]:
    with SCORES_CSV.open() as file:
        screen_scores = {
            row["path"]: float(row["rare_probability"]) for row in csv.DictReader(file)
        }
    return [
        ScreenedPhoto(
            shows_rare_cloud=label["label"] in RARE_LABELS,
            screen_score=screen_scores[label["path"]],
            vision_observation=vision_observation(label["type"], label["confidence"]),
        )
        for label in json.loads(VISION_MODEL_LABELS.read_text())
    ]


def cascade_observation_model(
    photos: list[ScreenedPhoto], ordinary_pass_rate: float
) -> ObservationModel:
    ordinary_scores = [
        photo.screen_score for photo in photos if not photo.shows_rare_cloud
    ]
    threshold = float(np.quantile(ordinary_scores, 1 - ordinary_pass_rate))

    def outcome_counts(shows_rare_cloud: bool) -> dict[SkyObservation, int]:
        counts = dict.fromkeys(SkyObservation, 0)
        for photo in photos:
            if photo.shows_rare_cloud != shows_rare_cloud:
                continue
            passed_screen = photo.screen_score > threshold
            counts[
                photo.vision_observation
                if passed_screen
                else SkyObservation.SCREENED_OUT
            ] += 1
        return counts

    return observation_model_from_counts(outcome_counts(True), outcome_counts(False))
