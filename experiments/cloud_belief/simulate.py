from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from experiments.cloud_belief.belief_filter import (
    VISION_MODEL_ON_COMMONS_PHOTOS,
    ObservationModel,
    SkyObservation,
    most_uncertain,
    onset_rate_per_minute,
    relaxed_beliefs,
    updated_beliefs,
)
from experiments.cloud_belief.cascade import (
    cascade_observation_model,
    read_screened_photos,
)

SKY_CELL_COUNT = 2000
FAVOURABLE_CELL_FRACTION = 0.05
FAVOURABLE_PRIOR = 0.05
BASELINE_PRIOR = 0.002
MEAN_DURATION_MINUTES = 60.0
MINUTES_PER_TICK = 1.0
TICKS = 1440
VISION_ONLY_LOOKS_PER_TICK = 20
SCREEN_PASS_RATES = (0.5, 0.25, 0.1)
ALERT_BELIEF = 0.5
SEEDS = range(5)

SamplingPolicy = Callable[[np.ndarray, int, int, np.random.Generator], np.ndarray]


def round_robin(
    beliefs: np.ndarray, looks: int, tick: int, rng: np.random.Generator
) -> np.ndarray:
    return (tick * looks + np.arange(looks)) % len(beliefs)


def proportional_to_belief(
    beliefs: np.ndarray, looks: int, tick: int, rng: np.random.Generator
) -> np.ndarray:
    return rng.choice(
        len(beliefs), size=looks, replace=False, p=beliefs / beliefs.sum()
    )


def highest_entropy(
    beliefs: np.ndarray, looks: int, tick: int, rng: np.random.Generator
) -> np.ndarray:
    return most_uncertain(beliefs, looks)


@dataclass(frozen=True)
class SimulationResult:
    events: int
    events_alerted: int
    present_minutes: int
    present_minutes_alerted: int
    alert_minutes: int
    vision_calls: int

    @property
    def event_recall(self) -> float:
        return self.events_alerted / self.events

    @property
    def minute_recall(self) -> float:
        return self.present_minutes_alerted / self.present_minutes

    @property
    def alert_precision(self) -> float:
        return self.present_minutes_alerted / self.alert_minutes

    @property
    def vision_calls_per_minute(self) -> float:
        return self.vision_calls / (TICKS * MINUTES_PER_TICK)


def simulate(
    policy: SamplingPolicy,
    looks_per_tick: int,
    true_priors: np.ndarray,
    assumed_priors: np.ndarray,
    observation_model: ObservationModel,
    rng: np.random.Generator,
) -> SimulationResult:
    observations = list(observation_model.given_present)
    present_probabilities = [observation_model.given_present[o] for o in observations]
    absent_probabilities = [observation_model.given_absent[o] for o in observations]
    log_likelihood_ratios = np.array(
        [observation_model.log_likelihood_ratio(o) for o in observations]
    )
    uses_vision_model = np.array(
        [observation is not SkyObservation.SCREENED_OUT for observation in observations]
    )
    onset_probability = 1 - np.exp(
        -onset_rate_per_minute(true_priors, MEAN_DURATION_MINUTES) * MINUTES_PER_TICK
    )
    ending_probability = 1 - np.exp(-MINUTES_PER_TICK / MEAN_DURATION_MINUTES)

    present = rng.random(len(true_priors)) < true_priors
    beliefs = assumed_priors.copy()
    alerted_this_event = np.zeros(len(true_priors), dtype=bool)
    events = events_alerted = vision_calls = 0
    present_minutes = present_minutes_alerted = alert_minutes = 0

    for tick in range(TICKS):
        change = rng.random(len(present))
        still_present = present & (change >= ending_probability)
        ended = present & ~still_present
        events += int(ended.sum())
        events_alerted += int((ended & alerted_this_event).sum())
        alerted_this_event &= ~ended
        present = still_present | (~present & (change < onset_probability))

        beliefs = relaxed_beliefs(
            beliefs, assumed_priors, MEAN_DURATION_MINUTES, MINUTES_PER_TICK
        )
        looked_at = policy(beliefs, looks_per_tick, tick, rng)
        seen = np.where(
            present[looked_at],
            rng.choice(len(observations), size=len(looked_at), p=present_probabilities),
            rng.choice(len(observations), size=len(looked_at), p=absent_probabilities),
        )
        vision_calls += int(uses_vision_model[seen].sum())
        beliefs[looked_at] = updated_beliefs(
            beliefs[looked_at], log_likelihood_ratios[seen]
        )

        alerting = beliefs >= ALERT_BELIEF
        alerted_this_event |= present & alerting
        present_minutes += int(present.sum())
        present_minutes_alerted += int((present & alerting).sum())
        alert_minutes += int(alerting.sum())

    events += int(present.sum())
    events_alerted += int((present & alerted_this_event).sum())
    return SimulationResult(
        events,
        events_alerted,
        present_minutes,
        present_minutes_alerted,
        alert_minutes,
        vision_calls,
    )


def print_mean_result(
    label: str,
    policy: SamplingPolicy,
    looks_per_tick: int,
    true_priors: np.ndarray,
    assumed_priors: np.ndarray,
    observation_model: ObservationModel,
) -> None:
    results = [
        simulate(
            policy,
            looks_per_tick,
            true_priors,
            assumed_priors,
            observation_model,
            np.random.default_rng(seed),
        )
        for seed in SEEDS
    ]
    print(
        f"{label:48s} {looks_per_tick:5d}  "
        f"{np.mean([r.vision_calls_per_minute for r in results]):6.1f}  "
        f"{np.mean([r.event_recall for r in results]):6.0%}  "
        f"{np.mean([r.minute_recall for r in results]):7.0%}  "
        f"{np.mean([r.alert_precision for r in results]):9.0%}"
    )


def main() -> None:
    favourable = np.arange(SKY_CELL_COUNT) < SKY_CELL_COUNT * FAVOURABLE_CELL_FRACTION
    true_priors = np.where(favourable, FAVOURABLE_PRIOR, BASELINE_PRIOR)
    flat_priors = np.full(SKY_CELL_COUNT, true_priors.mean())
    policies: dict[str, SamplingPolicy] = {
        "round robin": round_robin,
        "proportional to belief": proportional_to_belief,
        "highest entropy": highest_entropy,
    }
    print(
        f"{SKY_CELL_COUNT} sky cells, {TICKS} minutes, "
        f"mean event {MEAN_DURATION_MINUTES:.0f} min"
    )
    header = f"{'':48s} looks   calls  caught  minutes  precision"

    print(f"\nvision model on every look\n{header}")
    for knowledge, assumed_priors in (
        ("physical prior", true_priors),
        ("flat prior", flat_priors),
    ):
        for name, policy in policies.items():
            print_mean_result(
                f"{knowledge}, {name}",
                policy,
                VISION_ONLY_LOOKS_PER_TICK,
                true_priors,
                assumed_priors,
                VISION_MODEL_ON_COMMONS_PHOTOS,
            )

    photos = read_screened_photos()
    print(f"\nOpenCLIP screen first (physical prior, highest entropy)\n{header}")
    for pass_rate in SCREEN_PASS_RATES:
        cascade = cascade_observation_model(photos, pass_rate)
        for looks in (
            VISION_ONLY_LOOKS_PER_TICK,
            round(VISION_ONLY_LOOKS_PER_TICK / pass_rate),
        ):
            print_mean_result(
                f"screen passes {pass_rate:.0%} of ordinary frames",
                highest_entropy,
                looks,
                true_priors,
                true_priors,
                cascade,
            )


if __name__ == "__main__":
    main()
