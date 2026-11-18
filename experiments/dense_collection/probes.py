import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from experiments.encoder_comparison.evaluate import fit_logistic

DENSE_DIR = Path("output/dense")
PROBE_FILE = DENSE_DIR / "probes.npz"
SEED_EMBEDDINGS = "seed/openclip_b32_embeddings.npy"
SEED_FRAMES = "seed/frames.json"
SEED_SKY_LABELS = "seed/sky_feature_labels.json"
SEED_KEYS = (SEED_EMBEDDINGS, SEED_FRAMES, SEED_SKY_LABELS)
INVERSE_REGULARIZATION = 100.0
WHOLE_FRAME_VIEW = 0


@dataclass(frozen=True)
class Probe:
    weights: np.ndarray
    bias: float

    def view_logits(self, embeddings: np.ndarray) -> np.ndarray:
        return embeddings.astype(np.float32) @ self.weights + self.bias

    def max_view_probability(self, embeddings: np.ndarray) -> np.ndarray:
        return sigmoid(self.view_logits(embeddings).max(axis=1))

    def whole_frame_probability(self, embeddings: np.ndarray) -> np.ndarray:
        return sigmoid(self.view_logits(embeddings[:, WHOLE_FRAME_VIEW]))


@dataclass(frozen=True)
class Probes:
    gate: Probe
    sky: Probe


def sigmoid(logits: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-logits))


def train_probe(embeddings: np.ndarray, labels: np.ndarray) -> Probe:
    views = torch.from_numpy(embeddings).float()
    weights, bias = fit_logistic(
        views.flatten(0, 1),
        torch.from_numpy(labels).float().repeat_interleave(views.shape[1]),
        INVERSE_REGULARIZATION,
    )
    return Probe(weights.numpy(), float(bias))


def train_probes(
    embeddings: np.ndarray, frames: list[dict], sky_labels: dict[str, dict]
) -> Probes:
    is_rare = np.array([frame["rare_type"] is not None for frame in frames])
    labelled = [
        index for index, frame in enumerate(frames) if frame["path"] in sky_labels
    ]
    has_sky = np.array(
        [sky_labels[frames[index]["path"]]["sky_share"] != "none" for index in labelled]
    )
    return Probes(
        gate=train_probe(embeddings, is_rare),
        sky=train_probe(
            embeddings[labelled, WHOLE_FRAME_VIEW : WHOLE_FRAME_VIEW + 1], has_sky
        ),
    )


def seed_digest(etag: Callable[[str], str]) -> str:
    return hashlib.sha256("".join(etag(key) for key in SEED_KEYS).encode()).hexdigest()


def save_probes(path: Path, probes: Probes, digest: str) -> None:
    np.savez(
        path,
        gate_weights=probes.gate.weights,
        gate_bias=probes.gate.bias,
        sky_weights=probes.sky.weights,
        sky_bias=probes.sky.bias,
        seed_digest=digest,
    )


def read_probes(path: Path) -> tuple[Probes, str]:
    saved = np.load(path)
    probes = Probes(
        gate=Probe(saved["gate_weights"], float(saved["gate_bias"])),
        sky=Probe(saved["sky_weights"], float(saved["sky_bias"])),
    )
    return probes, str(saved["seed_digest"])


def load_probes(
    etag: Callable[[str], str], download: Callable[[str, Path], None]
) -> Probes:
    digest = seed_digest(etag)
    if PROBE_FILE.exists():
        probes, trained_on = read_probes(PROBE_FILE)
        if trained_on == digest:
            return probes
    for key in SEED_KEYS:
        download(key, DENSE_DIR / key)
    probes = train_probes(
        np.load(DENSE_DIR / SEED_EMBEDDINGS),
        json.loads((DENSE_DIR / SEED_FRAMES).read_text()),
        json.loads((DENSE_DIR / SEED_SKY_LABELS).read_text()),
    )
    save_probes(PROBE_FILE, probes, digest)
    return probes
