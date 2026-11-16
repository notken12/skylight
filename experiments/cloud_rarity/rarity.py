import argparse
import csv
import json
from collections import defaultdict

import numpy as np
import open_clip
import torch
from PIL import Image
from scipy.stats import rankdata

from backend.camera.view_scoring import (
    MODEL_NAME,
    MODEL_WEIGHTS,
    OpenClipImageEncoder,
)
from experiments.cloud_rarity.tiles import (
    EXPERIMENT_DIR,
    TILE_DIR,
    TILE_PIXELS,
    Tile,
    read_manifest,
)

TILE_LABELS = EXPERIMENT_DIR / "tile_labels.json"
GLOBAL_NEIGHBORS = 10
LOCAL_NEIGHBORS = 3
MAX_MISSING_FRACTION = 0.01
MISSING_PIXEL_LEVEL = 8
TILES_PER_ENCODING_BATCH = 8
QUERY_CHUNK_SIZE = 2048

CropBox = tuple[int, int, int, int]


def crop_boxes(crops_per_side: int) -> list[CropBox]:
    size = TILE_PIXELS * 2 // (crops_per_side + 1)
    offsets = np.linspace(0, TILE_PIXELS - size, crops_per_side).astype(int).tolist()
    return [(left, top, left + size, top + size) for top in offsets for left in offsets]


def missing_fraction(image: Image.Image) -> float:
    brightest_channel = np.asarray(image).max(axis=2)
    return float((brightest_channel < MISSING_PIXEL_LEVEL).mean())


def encode_crops(
    encoder: OpenClipImageEncoder, tiles: list[Tile], boxes: list[CropBox]
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    vectors: list[torch.Tensor] = []
    tile_indices: list[int] = []
    positions: list[int] = []
    for start in range(0, len(tiles), TILES_PER_ENCODING_BATCH):
        crops: list[Image.Image] = []
        for tile_index in range(
            start, min(start + TILES_PER_ENCODING_BATCH, len(tiles))
        ):
            with Image.open(TILE_DIR / tiles[tile_index].filename) as image:
                tile_image = image.convert("RGB")
            for position, box in enumerate(boxes):
                crop = tile_image.crop(box)
                if missing_fraction(crop) > MAX_MISSING_FRACTION:
                    continue
                crops.append(crop)
                tile_indices.append(tile_index)
                positions.append(position)
        if crops:
            vectors.append(encoder.encode_images(crops))
    return torch.cat(vectors), torch.tensor(tile_indices), torch.tensor(positions)


def neighbor_distance_excluding_own_tile(
    queries: torch.Tensor,
    query_tiles: torch.Tensor,
    references: torch.Tensor,
    reference_tiles: torch.Tensor,
    neighbors: int,
) -> torch.Tensor:
    distances = []
    for start in range(0, len(queries), QUERY_CHUNK_SIZE):
        chunk = slice(start, start + QUERY_CHUNK_SIZE)
        similarities = queries[chunk] @ references.T
        similarities[query_tiles[chunk, None] == reference_tiles[None, :]] = -1
        distances.append(1 - similarities.topk(neighbors, dim=1).values.mean(dim=1))
    return torch.cat(distances)


def highest_crop_score_per_tile(
    crop_scores: torch.Tensor, crop_tiles: torch.Tensor, tile_count: int
) -> torch.Tensor:
    return torch.full((tile_count,), -torch.inf).scatter_reduce(
        0, crop_tiles, crop_scores, reduce="amax"
    )


def local_crop_scores(
    tiles: list[Tile],
    vectors: torch.Tensor,
    crop_tiles: torch.Tensor,
    crop_positions: torch.Tensor,
) -> torch.Tensor:
    history: dict[tuple[float, float, int], list[int]] = defaultdict(list)
    candidates: dict[tuple[float, float, int], list[int]] = defaultdict(list)
    for crop, (tile_index, position) in enumerate(
        zip(crop_tiles.tolist(), crop_positions.tolist())
    ):
        tile = tiles[tile_index]
        if tile.role == "background":
            continue
        group = history if tile.role == "local" else candidates
        group[(tile.lat, tile.lon, position)].append(crop)

    scores = torch.full((len(vectors),), -torch.inf)
    for key, history_crops in history.items():
        if len(history_crops) <= LOCAL_NEIGHBORS:
            continue
        queries = history_crops + candidates[key]
        scores[queries] = neighbor_distance_excluding_own_tile(
            vectors[queries],
            crop_tiles[queries],
            vectors[history_crops],
            crop_tiles[history_crops],
            LOCAL_NEIGHBORS,
        )
    return scores


def auroc(positive_scores: list[float], negative_scores: list[float]) -> float:
    ranks = rankdata(positive_scores + negative_scores)
    positive_rank_sum = ranks[: len(positive_scores)].sum()
    pairs = len(positive_scores) * len(negative_scores)
    return float(
        (positive_rank_sum - len(positive_scores) * (len(positive_scores) + 1) / 2)
        / pairs
    )


def percentile(score: float, reference_scores: list[float]) -> float:
    return float(np.mean(np.asarray(reference_scores) < score))


def finite_scores(tile_scores: torch.Tensor, tile_indices: list[int]) -> list[float]:
    selected = tile_scores[tile_indices]
    return selected[selected.isfinite()].tolist()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops-per-side", type=int, default=3)
    crops_per_side = parser.parse_args().crops_per_side

    feature_visible: dict[str, bool] = json.loads(TILE_LABELS.read_text())
    tiles = read_manifest()
    model, _, preprocess = open_clip.create_model_and_transforms(
        MODEL_NAME, pretrained=MODEL_WEIGHTS
    )
    model.eval()
    vectors, crop_tiles, crop_positions = encode_crops(
        OpenClipImageEncoder(model, preprocess), tiles, crop_boxes(crops_per_side)
    )

    tile_groups: dict[str, list[int]] = defaultdict(list)
    for tile_index, tile in enumerate(tiles):
        if tile.role != "positive":
            tile_groups[tile.role].append(tile_index)
            continue
        visible = feature_visible[tile.filename]
        tile_groups["confirmed" if visible else "unconfirmed"].append(tile_index)

    crop_roles = [tiles[tile_index].role for tile_index in crop_tiles.tolist()]
    background_crops = [
        crop for crop, role in enumerate(crop_roles) if role == "background"
    ]
    global_queries = [crop for crop, role in enumerate(crop_roles) if role != "local"]
    global_tile_scores = highest_crop_score_per_tile(
        neighbor_distance_excluding_own_tile(
            vectors[global_queries],
            crop_tiles[global_queries],
            vectors[background_crops],
            crop_tiles[background_crops],
            GLOBAL_NEIGHBORS,
        ),
        crop_tiles[global_queries],
        len(tiles),
    )
    local_tile_scores = highest_crop_score_per_tile(
        local_crop_scores(tiles, vectors, crop_tiles, crop_positions),
        crop_tiles,
        len(tiles),
    )

    scored = {
        ("global", group): finite_scores(global_tile_scores, tile_groups[group])
        for group in ("confirmed", "unconfirmed", "background")
    } | {
        ("local", group): finite_scores(local_tile_scores, tile_groups[group])
        for group in ("confirmed", "unconfirmed", "local")
    }
    print(f"crops per side: {crops_per_side}, crops encoded: {len(vectors)}")
    for conditioning, reference in (("global", "background"), ("local", "local")):
        confirmed = scored[(conditioning, "confirmed")]
        unconfirmed = scored[(conditioning, "unconfirmed")]
        typical = scored[(conditioning, reference)]
        print(
            f"{conditioning}: confirmed={len(confirmed)} "
            f"unconfirmed={len(unconfirmed)} typical={len(typical)}"
        )
        print(f"  confirmed vs typical     {auroc(confirmed, typical):.3f}")
        print(f"  unconfirmed vs typical   {auroc(unconfirmed, typical):.3f}")
        print(f"  confirmed vs unconfirmed {auroc(confirmed, unconfirmed):.3f}")
        for quantile in (0.9, 0.95, 0.99):
            threshold = float(np.quantile(typical, quantile))
            above = sum(score > threshold for score in confirmed)
            print(f"  confirmed above typical p{quantile * 100:.0f}: {above}")

    scores_csv = EXPERIMENT_DIR / f"rarity_scores_{crops_per_side}x{crops_per_side}.csv"
    with scores_csv.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["filename", "feature_visible", "global_percentile", "local_percentile"]
        )
        for group in ("confirmed", "unconfirmed"):
            for tile_index in tile_groups[group]:
                writer.writerow(
                    [
                        tiles[tile_index].filename,
                        group == "confirmed",
                        round(
                            percentile(
                                global_tile_scores[tile_index].item(),
                                scored[("global", "background")],
                            ),
                            3,
                        ),
                        round(
                            percentile(
                                local_tile_scores[tile_index].item(),
                                scored[("local", "local")],
                            ),
                            3,
                        ),
                    ]
                )
    print(f"per-tile scores: {scores_csv}")


if __name__ == "__main__":
    main()
