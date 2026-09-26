import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from io import BytesIO
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import open_clip
import torch
from open_clip.model import CLIP
from PIL import Image
from torch.nn.functional import normalize

from blur_filter import MIN_LAPLACIAN_VARIANCE, laplacian_variance
from camera_image_scores import CameraImageScores, score_camera_image
from camera_matching import MatchedCamera
from camera_snapshots import CameraFrame, CameraSnapshot
from cameras import Camera

MODEL_NAME = "ViT-B-32"
MODEL_WEIGHTS = "laion2b_s34b_b79k"
REFERENCE_MANIFEST = Path(__file__).parent / "data/camera_view_samples/manifest.json"
SUNSET_REFERENCE_MANIFEST = (
    Path(__file__).parent / "data/sunset_view_samples/manifest.json"
)
SUNSET_MINIMUM_SCORE = 10
type PhenomenonType = Literal["storm", "sunset"]


def reference_digest() -> str:
    digest = hashlib.sha256()
    for manifest in (REFERENCE_MANIFEST, SUNSET_REFERENCE_MANIFEST):
        manifest_bytes = manifest.read_bytes()
        digest.update(manifest_bytes)
        for sample in json.loads(manifest_bytes)["samples"]:
            image = (manifest.parent / sample["filename"]).read_bytes()
            digest.update(hashlib.sha256(image).digest())
    return digest.hexdigest()[:16]


@dataclass(frozen=True)
class ReferenceScore:
    good_similarity: float
    bad_similarity: float
    margin: float
    threshold: float
    accepted: bool


@dataclass(frozen=True)
class ViewScore:
    storm_similarity: float
    rejected_similarity: float
    scenic_similarity: float
    poor_similarity: float
    margin: float
    threshold: float
    accepted: bool
    captured_at: str
    image_url: str


@dataclass(frozen=True)
class SunsetViewScore:
    good_similarity: float
    bad_similarity: float
    clip_margin: float
    combined_score: float
    threshold: float
    accepted: bool


@dataclass(frozen=True)
class PhenomenonResult:
    score: float
    visible: bool


@dataclass(frozen=True)
class ScoredCamera:
    camera: Camera
    event_ids: tuple[str, ...]
    view_score: ViewScore | None
    sunset_view_score: SunsetViewScore | None
    frame: CameraFrame | None
    sharpness: float | None
    image_scores: CameraImageScores | None

    @property
    def phenomena(self) -> dict[PhenomenonType, PhenomenonResult]:
        phenomena = {}
        if self.view_score is not None:
            phenomena["storm"] = PhenomenonResult(
                self.view_score.margin, self.view_score.accepted
            )
        if self.sunset_view_score is not None:
            phenomena["sunset"] = PhenomenonResult(
                self.sunset_view_score.combined_score,
                self.sunset_view_score.accepted,
            )
        return phenomena


@dataclass(frozen=True)
class Calibration:
    threshold: float
    true_positives: int
    positive_count: int
    true_negatives: int
    negative_count: int


def leave_one_out_margins(vectors: torch.Tensor, positive: list[int]) -> list[float]:
    positive_set = set(positive)
    negative = [index for index in range(len(vectors)) if index not in positive_set]
    if len(positive) < 2 or len(negative) < 2:
        raise ValueError("Calibration needs at least two positive and negative images")

    similarities = vectors @ vectors.T
    margins = []
    for index in range(len(vectors)):
        positive_peers = [peer for peer in positive if peer != index]
        negative_peers = [peer for peer in negative if peer != index]
        good_mean = similarities[index, positive_peers].mean().item()
        bad_mean = similarities[index, negative_peers].mean().item()
        margins.append(good_mean - bad_mean)
    return margins


def calibrated_threshold(scores: list[float], positive: list[int]) -> Calibration:
    positive_set = set(positive)
    negative = [index for index in range(len(scores)) if index not in positive_set]
    if len(positive) < 2 or len(negative) < 2:
        raise ValueError("Calibration needs at least two positive and negative images")

    ordered = sorted(set(scores))
    thresholds = [
        ordered[0] - 1,
        *(sum(pair) / 2 for pair in pairwise(ordered)),
        ordered[-1] + 1,
    ]

    def evaluate(threshold: float) -> tuple[float, int, float, Calibration]:
        true_positives = sum(scores[index] >= threshold for index in positive)
        true_negatives = sum(scores[index] < threshold for index in negative)
        balanced_accuracy = (
            true_positives / len(positive) + true_negatives / len(negative)
        ) / 2
        calibration = Calibration(
            threshold=threshold,
            true_positives=true_positives,
            positive_count=len(positive),
            true_negatives=true_negatives,
            negative_count=len(negative),
        )
        return balanced_accuracy, true_positives, -threshold, calibration

    return max(
        (evaluate(threshold) for threshold in thresholds), key=lambda result: result[:3]
    )[3]


def reference_groups(
    samples: list[dict[str, Any]],
) -> tuple[list[int], list[int], list[int]]:
    positive = []
    scenic = []
    poor = []
    for index, sample in enumerate(samples):
        presence = sample["storm_presence"]
        quality = sample["view_quality"]
        if quality == "poor" and presence in {"storm_view", "unknown"}:
            poor.append(index)
        elif presence == "storm_view" and quality == "good":
            positive.append(index)
        elif presence == "no_storm" and quality == "good":
            scenic.append(index)
        else:
            raise ValueError(f"Unsupported reference labels: {presence}, {quality}")
    return positive, scenic, poor


class OpenClipImageEncoder:
    def __init__(
        self, model: CLIP, preprocess: Callable[[Image.Image], torch.Tensor]
    ) -> None:
        self.model = model
        self.preprocess = preprocess

    def encode(self, images: list[bytes]) -> torch.Tensor:
        prepared = []
        for payload in images:
            with Image.open(BytesIO(payload)) as image:
                prepared.append(self.preprocess(image.convert("RGB")))
        with torch.inference_mode():
            return normalize(
                self.model.encode_image(torch.stack(prepared)).float(), dim=-1
            )


class OpenClipReferenceScorer:
    def __init__(self, good: torch.Tensor, bad: torch.Tensor) -> None:
        self.good_count = len(good)
        self.bad_count = len(bad)
        self.good_mean = good.mean(dim=0)
        self.bad_mean = bad.mean(dim=0)
        self.calibration = calibrated_threshold(
            leave_one_out_margins(torch.cat((good, bad)), list(range(len(good)))),
            list(range(len(good))),
        )

    def score(self, vectors: torch.Tensor) -> list[ReferenceScore]:
        scores = []
        for vector in vectors:
            good_similarity = (vector @ self.good_mean).item()
            bad_similarity = (vector @ self.bad_mean).item()
            margin = good_similarity - bad_similarity
            scores.append(
                ReferenceScore(
                    good_similarity=round(good_similarity, 4),
                    bad_similarity=round(bad_similarity, 4),
                    margin=round(margin, 4),
                    threshold=round(self.calibration.threshold, 4),
                    accepted=margin >= self.calibration.threshold,
                )
            )
        return scores


class OpenClipViewScorer:
    def __init__(
        self,
        reference_scorer: OpenClipReferenceScorer,
        scenic_vectors: torch.Tensor,
        poor_vectors: torch.Tensor,
    ) -> None:
        self.reference_scorer = reference_scorer
        self.storm_count = reference_scorer.good_count
        self.scenic_count = len(scenic_vectors)
        self.poor_count = len(poor_vectors)
        self.scenic_mean = scenic_vectors.mean(dim=0)
        self.poor_mean = poor_vectors.mean(dim=0)
        self.calibration = reference_scorer.calibration

    def score(
        self, snapshots: list[CameraSnapshot], vectors: torch.Tensor
    ) -> list[ViewScore]:
        reference_scores = self.reference_scorer.score(vectors)
        scores = []
        for snapshot, vector, reference in zip(
            snapshots, vectors, reference_scores, strict=True
        ):
            scores.append(
                ViewScore(
                    storm_similarity=reference.good_similarity,
                    rejected_similarity=reference.bad_similarity,
                    scenic_similarity=round((vector @ self.scenic_mean).item(), 4),
                    poor_similarity=round((vector @ self.poor_mean).item(), 4),
                    margin=reference.margin,
                    threshold=reference.threshold,
                    accepted=reference.accepted,
                    captured_at=snapshot.captured_at,
                    image_url=snapshot.image_url,
                )
            )
        return scores


class SunsetViewScorer:
    def __init__(
        self,
        reference_scorer: OpenClipReferenceScorer,
        reference_vectors: torch.Tensor,
        reference_images: list[bytes],
    ) -> None:
        self.reference_scorer = reference_scorer
        self.good_count = reference_scorer.good_count
        self.bad_count = reference_scorer.bad_count
        margins = leave_one_out_margins(reference_vectors, list(range(self.good_count)))
        warm_tones = [
            score_camera_image(image).warm_tone_strength for image in reference_images
        ]
        self.calibration = calibrated_threshold(
            [
                margin + warmth
                for margin, warmth in zip(margins, warm_tones, strict=True)
            ],
            list(range(self.good_count)),
        )

    def score(
        self, vectors: torch.Tensor, image_scores: list[CameraImageScores]
    ) -> list[SunsetViewScore]:
        references = self.reference_scorer.score(vectors)
        scores = []
        for reference, image_score in zip(references, image_scores, strict=True):
            combined = reference.margin + image_score.warm_tone_strength
            scores.append(
                SunsetViewScore(
                    good_similarity=reference.good_similarity,
                    bad_similarity=reference.bad_similarity,
                    clip_margin=reference.margin,
                    combined_score=round(combined, 4),
                    threshold=round(self.calibration.threshold, 4),
                    accepted=combined >= self.calibration.threshold,
                )
            )
        return scores


def load_view_scorers() -> tuple[
    OpenClipImageEncoder, OpenClipViewScorer, SunsetViewScorer
]:
    storm_samples = json.loads(REFERENCE_MANIFEST.read_text())["samples"]
    sunset_samples = json.loads(SUNSET_REFERENCE_MANIFEST.read_text())["samples"]
    positive, scenic, poor = reference_groups(storm_samples)
    if not scenic or not poor:
        raise ValueError("Both scenic and poor-quality references are required")
    sunset_good = [
        index
        for index, sample in enumerate(sunset_samples)
        if sample["label"] == "good"
    ]
    sunset_bad = [
        index for index, sample in enumerate(sunset_samples) if sample["label"] == "bad"
    ]
    if len(sunset_good) + len(sunset_bad) != len(sunset_samples):
        raise ValueError("Sunset references must be labeled good or bad")

    model, _, preprocess = open_clip.create_model_and_transforms(
        MODEL_NAME, pretrained=MODEL_WEIGHTS
    )
    model.eval()
    encoder = OpenClipImageEncoder(model, preprocess)
    storm_images = [
        (REFERENCE_MANIFEST.parent / sample["filename"]).read_bytes()
        for sample in storm_samples
    ]
    sunset_images = [
        (SUNSET_REFERENCE_MANIFEST.parent / sample["filename"]).read_bytes()
        for sample in sunset_samples
    ]
    reference_vectors = encoder.encode(storm_images + sunset_images)
    storm_vectors = reference_vectors[: len(storm_images)]
    sunset_vectors = reference_vectors[len(storm_images) :]
    storm_scorer = OpenClipViewScorer(
        OpenClipReferenceScorer(storm_vectors[positive], storm_vectors[scenic + poor]),
        storm_vectors[scenic],
        storm_vectors[poor],
    )
    sunset_bad_vectors = torch.cat(
        (sunset_vectors[sunset_bad], storm_vectors[scenic + poor])
    )
    sunset_reference_vectors = torch.cat(
        (sunset_vectors[sunset_good], sunset_bad_vectors)
    )
    sunset_reference_images = (
        [sunset_images[index] for index in sunset_good]
        + [sunset_images[index] for index in sunset_bad]
        + [storm_images[index] for index in scenic + poor]
    )
    sunset_scorer = SunsetViewScorer(
        OpenClipReferenceScorer(sunset_vectors[sunset_good], sunset_bad_vectors),
        sunset_reference_vectors,
        sunset_reference_images,
    )
    return encoder, storm_scorer, sunset_scorer


def score_cameras(
    matches: list[MatchedCamera],
    sunset_quality: tuple[int, ...],
    extra_snapshot_indices: set[int],
    fetch_snapshot: Callable[[Camera], CameraSnapshot],
    encode_images: Callable[[list[bytes]], torch.Tensor],
    score_storm_views: Callable[[list[CameraSnapshot], torch.Tensor], list[ViewScore]],
    score_sunset_views: Callable[
        [torch.Tensor, list[CameraImageScores]], list[SunsetViewScore]
    ],
) -> list[ScoredCamera]:
    if len(matches) != len(sunset_quality):
        raise ValueError("Camera matches and sunset scores must have the same length")
    cameras = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for start in range(0, len(matches), 32):
            batch = matches[start : start + 32]
            candidate_positions = [
                position
                for position, match in enumerate(batch)
                if not match.camera.link_only
                and (
                    match.event_ids
                    or sunset_quality[start + position] >= SUNSET_MINIMUM_SCORE
                    or start + position in extra_snapshot_indices
                )
            ]
            snapshots = list(
                executor.map(
                    fetch_snapshot,
                    (batch[position].camera for position in candidate_positions),
                )
            )
            sharpness = {
                position: round(laplacian_variance(snapshot.image), 2)
                for position, snapshot in zip(
                    candidate_positions, snapshots, strict=True
                )
            }
            image_scores = {
                position: score_camera_image(snapshot.image)
                for position, snapshot in zip(
                    candidate_positions, snapshots, strict=True
                )
            }
            sharp_candidates = [
                (position, snapshot)
                for position, snapshot in zip(
                    candidate_positions, snapshots, strict=True
                )
                if sharpness[position] >= MIN_LAPLACIAN_VARIANCE
                and (
                    batch[position].event_ids
                    or sunset_quality[start + position] >= SUNSET_MINIMUM_SCORE
                )
            ]
            storm_scores: dict[int, ViewScore] = {}
            sunset_scores: dict[int, SunsetViewScore] = {}
            if sharp_candidates:
                vectors = encode_images(
                    [snapshot.image for _, snapshot in sharp_candidates]
                )
                storm_positions = [
                    index
                    for index, (position, _) in enumerate(sharp_candidates)
                    if batch[position].event_ids
                ]
                sunset_positions = [
                    index
                    for index, (position, _) in enumerate(sharp_candidates)
                    if sunset_quality[start + position] >= SUNSET_MINIMUM_SCORE
                ]
                storm_scores = dict(
                    zip(
                        (sharp_candidates[index][0] for index in storm_positions),
                        score_storm_views(
                            [sharp_candidates[index][1] for index in storm_positions],
                            vectors[storm_positions],
                        ),
                        strict=True,
                    )
                )
                sunset_scores = dict(
                    zip(
                        (sharp_candidates[index][0] for index in sunset_positions),
                        score_sunset_views(
                            vectors[sunset_positions],
                            [
                                image_scores[sharp_candidates[index][0]]
                                for index in sunset_positions
                            ],
                        ),
                        strict=True,
                    )
                )
            frames = {
                position: CameraFrame(snapshot.image_url, snapshot.captured_at)
                for position, snapshot in zip(
                    candidate_positions, snapshots, strict=True
                )
            }
            for position, match in enumerate(batch):
                cameras.append(
                    ScoredCamera(
                        match.camera,
                        match.event_ids,
                        storm_scores.get(position),
                        sunset_scores.get(position),
                        frames.get(position),
                        sharpness.get(position),
                        image_scores.get(position),
                    )
                )
    return cameras


def include_camera_frames(
    cameras: list[ScoredCamera],
    required_indices: set[int],
    fetch_frame: Callable[[Camera], CameraFrame],
) -> list[ScoredCamera]:
    faa_sites: dict[tuple[float, float], list[int]] = defaultdict(list)
    for index, scored in enumerate(cameras):
        if scored.camera.network == "FAA WeatherCams":
            faa_sites[(scored.camera.latitude, scored.camera.longitude)].append(index)

    frame_indices = set(required_indices)
    for site_indices in faa_sites.values():
        if len(site_indices) > 1 and any(
            cameras[index].frame is not None or index in required_indices
            for index in site_indices
        ):
            frame_indices.update(site_indices)

    missing_indices = sorted(
        index
        for index in frame_indices
        if cameras[index].frame is None and not cameras[index].camera.link_only
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        frames = list(
            executor.map(
                fetch_frame,
                (cameras[index].camera for index in missing_indices),
            )
        )

    with_frames = cameras.copy()
    for index, frame in zip(missing_indices, frames, strict=True):
        with_frames[index] = replace(cameras[index], frame=frame)
    return with_frames
