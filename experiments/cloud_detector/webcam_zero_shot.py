import csv

import numpy as np

from experiments.cloud_detector.photos import EXPERIMENT_DIR, RARE_LABELS
from experiments.cloud_detector.webcam_frames import read_manifest
from experiments.cloud_detector.zero_shot import (
    FALSE_ALARM_RATES,
    SCORES_CSV,
    write_scores,
    zero_shot_scores,
)

WEBCAM_SCORES_CSV = EXPERIMENT_DIR / "webcam_zero_shot_scores.csv"


def commons_ordinary_scores() -> list[float]:
    with SCORES_CSV.open() as file:
        return [
            float(row["rare_probability"])
            for row in csv.DictReader(file)
            if row["label"] not in RARE_LABELS
        ]


def main() -> None:
    frames = read_manifest()
    scores = zero_shot_scores(frames)
    write_scores(WEBCAM_SCORES_CSV, frames, scores)
    frame_scores = np.asarray([score.rare_probability for score in scores])
    ordinary_scores = commons_ordinary_scores()
    print(f"live webcam frames: {len(frames)}")
    for rate in FALSE_ALARM_RATES:
        threshold = float(np.quantile(ordinary_scores, 1 - rate))
        flagged = int((frame_scores > threshold).sum())
        print(
            f"threshold with {rate:.0%} false alarms on Commons ordinary photos "
            f"({threshold:.3f}): {flagged} frames flagged ({flagged / len(frames):.0%})"
        )
    print(f"per-frame scores: {WEBCAM_SCORES_CSV}")


if __name__ == "__main__":
    main()
