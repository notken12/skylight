import argparse
import json
import random
from collections.abc import Callable

import numpy as np
import torch
from torch.nn.functional import binary_cross_entropy_with_logits

from experiments.cloud_rarity.rarity import auroc
from experiments.encoder_comparison.embed import EMBEDDING_DIR
from experiments.encoder_comparison.frames import COMPARISON_DIR, Frame, all_frames

SKY_FEATURE_LABELS = COMPARISON_DIR / "sky_feature_labels.json"
RESULTS = COMPARISON_DIR / "results.json"
FOLD_COUNT = 5
FOLD_SEED = 0
FALSE_ALARM_RATE = 0.02
MIN_EXAMPLES_PER_CLASS = 15
WHOLE_FRAME_VIEW = slice(0, 1)
ALL_VIEWS = slice(None)
VIEW_SETS = {"whole": WHOLE_FRAME_VIEW, "tiles": ALL_VIEWS}

SKY_FEATURES: dict[str, Callable[[dict], bool]] = {
    "sky_visible": lambda label: label["sky_share"] != "none",
    "mostly_cloudy": lambda label: label["cloud_cover"] in ("broken", "overcast"),
    "clear_or_few": lambda label: label["cloud_cover"] in ("clear", "few"),
    "low_cloud": lambda label: label["low_cloud"],
    "mid_cloud": lambda label: label["mid_cloud"],
    "high_cloud": lambda label: label["high_cloud"],
    "wave_texture": lambda label: label["wave_texture"],
    "cap_cloud": lambda label: label["cap_cloud"],
    "deep_convection": lambda label: label["convection"] in ("towering", "anvil"),
    "precipitation": lambda label: label["precipitation"],
    "obstructed": lambda label: label["obstruction"] != "none",
}


def fit_logistic(
    features: torch.Tensor, labels: torch.Tensor, inverse_regularization: float
) -> tuple[torch.Tensor, torch.Tensor]:
    weights = torch.zeros(features.shape[1], requires_grad=True)
    bias = torch.zeros(1, requires_grad=True)
    optimizer = torch.optim.LBFGS([weights, bias], max_iter=200)
    penalty = 1 / (2 * inverse_regularization * len(labels))

    def loss_step() -> torch.Tensor:
        optimizer.zero_grad()
        loss = (
            binary_cross_entropy_with_logits(features @ weights + bias, labels)
            + penalty * weights.square().sum()
        )
        loss.backward()
        return loss

    optimizer.step(loss_step)
    return weights.detach(), bias.detach()


def camera_folds(cameras: list[str]) -> list[np.ndarray]:
    distinct = sorted(set(cameras))
    random.Random(FOLD_SEED).shuffle(distinct)
    fold_of = {camera: index % FOLD_COUNT for index, camera in enumerate(distinct)}
    assigned = np.array([fold_of[camera] for camera in cameras])
    return [np.flatnonzero(assigned == fold) for fold in range(FOLD_COUNT)]


def held_out_scores(
    embeddings: np.ndarray,
    labels: np.ndarray,
    cameras: list[str],
    views: slice,
    inverse_regularization: float,
) -> np.ndarray:
    viewed = torch.from_numpy(embeddings[:, views]).float()
    targets = torch.from_numpy(labels).float()
    scores = np.empty(len(labels))
    for test in camera_folds(cameras):
        train = np.setdiff1d(np.arange(len(labels)), test)
        train_views = viewed[train]
        weights, bias = fit_logistic(
            train_views.flatten(0, 1),
            targets[train].repeat_interleave(train_views.shape[1]),
            inverse_regularization,
        )
        scores[test] = (viewed[test] @ weights + bias).amax(dim=1).numpy()
    return scores


def recall_at_false_alarm_rate(
    positive_scores: np.ndarray, negative_scores: np.ndarray
) -> float:
    threshold = np.quantile(negative_scores, 1 - FALSE_ALARM_RATE)
    return float((positive_scores > threshold).mean())


def rare_label_results(
    frames: list[Frame],
    embeddings: np.ndarray,
    views: slice,
    inverse_regularization: float,
) -> dict[str, float]:
    is_rare = np.array([frame.rare_type is not None for frame in frames])
    scores = held_out_scores(
        embeddings,
        is_rare,
        [frame.camera for frame in frames],
        views,
        inverse_regularization,
    )

    def where(condition: Callable[[Frame], bool]) -> np.ndarray:
        return np.array([condition(frame) for frame in frames])

    webcam = where(lambda frame: frame.is_webcam)
    alpine = where(lambda frame: frame.source == "alpine")
    commons = where(lambda frame: frame.source == "commons")
    lenticular = where(lambda frame: frame.rare_type == "lenticular")
    noctilucent = where(lambda frame: frame.rare_type == "noctilucent")
    webcam_ordinary = scores[webcam & ~is_rare]
    return {
        "commons_auroc": auroc(
            scores[commons & is_rare].tolist(), scores[commons & ~is_rare].tolist()
        ),
        "webcam_auroc": auroc(
            scores[webcam & is_rare].tolist(), webcam_ordinary.tolist()
        ),
        "webcam_recall": recall_at_false_alarm_rate(
            scores[webcam & is_rare], webcam_ordinary
        ),
        "webcam_lenticular_recall": recall_at_false_alarm_rate(
            scores[webcam & lenticular], webcam_ordinary
        ),
        "webcam_noctilucent_recall": recall_at_false_alarm_rate(
            scores[webcam & noctilucent], webcam_ordinary
        ),
        "alpine_lenticular_recall": recall_at_false_alarm_rate(
            scores[alpine & is_rare], scores[alpine & ~is_rare]
        ),
        "alpine_lenticular_auroc": auroc(
            scores[alpine & is_rare].tolist(), scores[alpine & ~is_rare].tolist()
        ),
    }


def sky_feature_results(
    frames: list[Frame],
    embeddings: np.ndarray,
    views: slice,
    inverse_regularization: float,
) -> dict[str, float]:
    sky_labels: dict[str, dict] = json.loads(SKY_FEATURE_LABELS.read_text())
    labelled = [index for index, frame in enumerate(frames) if frame.path in sky_labels]
    cameras = [frames[index].camera for index in labelled]
    results = {}
    for feature, is_present in SKY_FEATURES.items():
        present = np.array(
            [bool(is_present(sky_labels[frames[index].path])) for index in labelled]
        )
        if min(present.sum(), (~present).sum()) < MIN_EXAMPLES_PER_CLASS:
            continue
        scores = held_out_scores(
            embeddings[labelled], present, cameras, views, inverse_regularization
        )
        results[feature] = auroc(scores[present].tolist(), scores[~present].tolist())
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=["rare_label", "sky_features"])
    parser.add_argument("--inverse-regularization", type=float, default=10.0)
    arguments = parser.parse_args()
    task = arguments.task
    evaluate = rare_label_results if task == "rare_label" else sky_feature_results
    frames = all_frames()
    results = {
        f"{path.stem}/{view_name}": evaluate(
            frames, np.load(path), views, arguments.inverse_regularization
        )
        for path in sorted(EMBEDDING_DIR.glob("*.npy"))
        for view_name, views in VIEW_SETS.items()
    }
    saved = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    RESULTS.write_text(
        json.dumps(
            saved | {f"{task}/C={arguments.inverse_regularization:g}": results},
            indent=1,
        )
    )
    metrics = list(next(iter(results.values())))
    print(
        f"{'encoder/views':24s}" + "".join(f"{metric[:12]:>14s}" for metric in metrics)
    )
    for name, values in results.items():
        print(f"{name:24s}" + "".join(f"{values[metric]:14.2f}" for metric in metrics))
    print(f"{'mean':24s}", end="")
    print(
        "  ".join(
            f"{name}={np.mean(list(values.values())):.3f}"
            for name, values in results.items()
        )
    )


if __name__ == "__main__":
    main()
