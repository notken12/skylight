from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import log

import numpy as np


class SkyObservation(StrEnum):
    SCREENED_OUT = "screened_out"
    CONFIDENT_NONE = "confident_none"
    UNSURE_NONE = "unsure_none"
    UNSURE_RARE = "unsure_rare"
    CONFIDENT_RARE = "confident_rare"


@dataclass(frozen=True)
class ObservationModel:
    given_present: Mapping[SkyObservation, float]
    given_absent: Mapping[SkyObservation, float]

    def log_likelihood_ratio(self, observation: SkyObservation) -> float:
        return log(self.given_present[observation] / self.given_absent[observation])


def observation_model_from_counts(
    present_counts: Mapping[SkyObservation, int],
    absent_counts: Mapping[SkyObservation, int],
) -> ObservationModel:
    def smoothed(counts: Mapping[SkyObservation, int]) -> dict[SkyObservation, float]:
        total = sum(counts.values()) + 0.5 * len(counts)
        return {
            observation: (count + 0.5) / total for observation, count in counts.items()
        }

    return ObservationModel(smoothed(present_counts), smoothed(absent_counts))


VISION_MODEL_ON_COMMONS_PHOTOS = observation_model_from_counts(
    present_counts={
        SkyObservation.CONFIDENT_NONE: 20,
        SkyObservation.UNSURE_NONE: 12,
        SkyObservation.UNSURE_RARE: 14,
        SkyObservation.CONFIDENT_RARE: 38,
    },
    absent_counts={
        SkyObservation.CONFIDENT_NONE: 55,
        SkyObservation.UNSURE_NONE: 10,
        SkyObservation.UNSURE_RARE: 1,
        SkyObservation.CONFIDENT_RARE: 0,
    },
)


def onset_rate_per_minute(
    priors: np.ndarray, mean_duration_minutes: float
) -> np.ndarray:
    return priors / ((1 - priors) * mean_duration_minutes)


def relaxed_beliefs(
    beliefs: np.ndarray,
    priors: np.ndarray,
    mean_duration_minutes: float,
    elapsed_minutes: float,
) -> np.ndarray:
    change_rate = (
        onset_rate_per_minute(priors, mean_duration_minutes) + 1 / mean_duration_minutes
    )
    return priors + (beliefs - priors) * np.exp(-change_rate * elapsed_minutes)


def updated_beliefs(
    beliefs: np.ndarray, log_likelihood_ratios: np.ndarray
) -> np.ndarray:
    log_odds = np.log(beliefs / (1 - beliefs)) + log_likelihood_ratios
    return 1 / (1 + np.exp(-log_odds))


def belief_entropy_bits(beliefs: np.ndarray) -> np.ndarray:
    return -(beliefs * np.log2(beliefs) + (1 - beliefs) * np.log2(1 - beliefs))


def most_uncertain(beliefs: np.ndarray, count: int) -> np.ndarray:
    return np.argpartition(-belief_entropy_bits(beliefs), count - 1)[:count]
