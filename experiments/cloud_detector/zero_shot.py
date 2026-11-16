import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
import open_clip
import torch
from torch.nn.functional import normalize

from backend.camera.view_scoring import (
    MODEL_NAME,
    MODEL_WEIGHTS,
    OpenClipImageEncoder,
)
from experiments.cloud_detector.photos import (
    EXPERIMENT_DIR,
    RARE_LABELS,
    Photo,
    read_manifest,
)
from experiments.cloud_rarity.rarity import auroc

SCORES_CSV = EXPERIMENT_DIR / "zero_shot_scores.csv"
ENCODING_BATCH_SIZE = 64
LOGIT_SCALE = 100.0
FALSE_ALARM_RATES = (0.05, 0.01)

RARE_PROMPTS = {
    "mammatus": "a photo of mammatus clouds, pouches hanging under a cloud base",
    "lenticular": "a photo of a lenticular cloud, a smooth lens-shaped cloud",
    "asperitas": "a photo of asperitas clouds, a dark wavy turbulent cloud base",
    "kelvin_helmholtz": "a photo of Kelvin-Helmholtz clouds shaped like breaking waves",
    "fallstreak_hole": "a photo of a fallstreak hole, a round gap punched in a cloud layer",
    "shelf_cloud": "a photo of a shelf cloud, a low wedge-shaped arcus cloud",
    "roll_cloud": "a photo of a roll cloud, a long horizontal tube-shaped cloud",
    "noctilucent": "a photo of noctilucent clouds glowing at night",
}
ORDINARY_PROMPTS = [
    "a photo of ordinary cumulus clouds",
    "a photo of a clear blue sky",
    "a photo of a grey overcast sky",
    "a photo of thin cirrus clouds",
    "a photo of stratocumulus clouds",
    "a photo of altocumulus clouds",
    "a photo of a thunderstorm cloud",
    "a landscape photo with an unremarkable sky",
]


def encode_prompts(model: open_clip.CLIP, prompts: list[str]) -> torch.Tensor:
    tokens = open_clip.get_tokenizer(MODEL_NAME)(prompts)
    with torch.inference_mode():
        return normalize(model.encode_text(tokens).float(), dim=-1)


def encode_photos(encoder: OpenClipImageEncoder, photos: list[Photo]) -> torch.Tensor:
    payloads = [Path(photo.path).read_bytes() for photo in photos]
    return torch.cat(
        [
            encoder.encode(payloads[start : start + ENCODING_BATCH_SIZE])
            for start in range(0, len(payloads), ENCODING_BATCH_SIZE)
        ]
    )


def main() -> None:
    photos = read_manifest()
    model, _, preprocess = open_clip.create_model_and_transforms(
        MODEL_NAME, pretrained=MODEL_WEIGHTS
    )
    model.eval()
    rare_labels = list(RARE_PROMPTS)
    prompt_vectors = encode_prompts(
        model, [RARE_PROMPTS[label] for label in rare_labels] + ORDINARY_PROMPTS
    )
    photo_vectors = encode_photos(OpenClipImageEncoder(model, preprocess), photos)
    probabilities = (LOGIT_SCALE * photo_vectors @ prompt_vectors.T).softmax(dim=1)
    rare_class_probabilities = probabilities[:, : len(rare_labels)]
    rare_probability = rare_class_probabilities.sum(dim=1).tolist()
    predicted_label = [
        rare_labels[index] for index in rare_class_probabilities.argmax(dim=1).tolist()
    ]

    scores_by_label: dict[str, list[float]] = defaultdict(list)
    scores_by_source: dict[str, list[float]] = defaultdict(list)
    correct_type_by_label: dict[str, int] = defaultdict(int)
    for photo, score, predicted in zip(photos, rare_probability, predicted_label):
        scores_by_label[photo.label].append(score)
        correct_type_by_label[photo.label] += predicted == photo.label
        if photo.label not in RARE_LABELS:
            scores_by_source[photo.label].append(score)
    rare_scores = [s for label in RARE_LABELS for s in scores_by_label[label]]
    ordinary_scores = [s for scores in scores_by_source.values() for s in scores]

    print(f"rare photos: {len(rare_scores)}, ordinary photos: {len(ordinary_scores)}")
    print(f"rare vs ordinary AUROC: {auroc(rare_scores, ordinary_scores):.3f}")
    thresholds = {
        rate: float(np.quantile(ordinary_scores, 1 - rate))
        for rate in FALSE_ALARM_RATES
    }
    for rate, threshold in thresholds.items():
        hit_rate = float(np.mean(np.asarray(rare_scores) > threshold))
        print(
            f"false alarms {rate:.0%}: hit rate {hit_rate:.0%}, "
            f"likelihood ratio {hit_rate / rate:.1f}"
        )
    print("per rare type: count, hit rate at 5% false alarms, correct type named")
    for label in RARE_LABELS:
        scores = np.asarray(scores_by_label[label])
        print(
            f"  {label:18s} {len(scores):3d}  {np.mean(scores > thresholds[0.05]):.0%}"
            f"  {correct_type_by_label[label] / len(scores):.0%}"
        )
    print("per ordinary source: count, false alarms at the pooled 5% threshold")
    for label, scores in scores_by_source.items():
        false_alarms = float(np.mean(np.asarray(scores) > thresholds[0.05]))
        print(f"  {label:18s} {len(scores):3d}  {false_alarms:.0%}")

    with SCORES_CSV.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["path", "label", "rare_probability", "predicted_type"])
        for photo, score, predicted in zip(photos, rare_probability, predicted_label):
            writer.writerow([photo.path, photo.label, round(score, 4), predicted])
    print(f"per-photo scores: {SCORES_CSV}")


if __name__ == "__main__":
    main()
