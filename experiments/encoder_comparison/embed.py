import argparse
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import open_clip
import timm
import torch
from PIL import Image
from timm.data import create_transform, resolve_data_config
from torch.nn.functional import normalize

from experiments.encoder_comparison.frames import COMPARISON_DIR, Frame, all_frames

EMBEDDING_DIR = COMPARISON_DIR / "embeddings"
SKY_HEIGHT_FRACTION = 0.7
TILE_COLUMNS = 3
TILE_ROWS = 2
FRAMES_PER_BATCH = 16

type Preprocess = Callable[[Image.Image], torch.Tensor]
type EncodeBatch = Callable[[torch.Tensor], torch.Tensor]


@dataclass(frozen=True)
class Encoder:
    preprocess: Preprocess
    encode: EncodeBatch


def open_clip_encoder(model_name: str, pretrained: str, device: str) -> Encoder:
    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name, pretrained=pretrained
    )
    model = model.eval().to(device)
    return Encoder(preprocess, model.encode_image)


def timm_encoder(model_name: str, device: str) -> Encoder:
    model = timm.create_model(model_name, pretrained=True, num_classes=0, img_size=224)
    model = model.eval().to(device)
    preprocess = create_transform(
        **resolve_data_config({"input_size": (3, 224, 224)}, model=model)
    )
    return Encoder(preprocess, model)


ENCODER_LOADERS: dict[str, Callable[[str], Encoder]] = {
    "openclip_b32": lambda device: open_clip_encoder(
        "ViT-B-32", "laion2b_s34b_b79k", device
    ),
    "openclip_b16": lambda device: open_clip_encoder(
        "ViT-B-16", "laion2b_s34b_b88k", device
    ),
    "siglip2_b16": lambda device: open_clip_encoder(
        "ViT-B-16-SigLIP2-256", "webli", device
    ),
    "dinov2_b14": lambda device: timm_encoder(
        "vit_base_patch14_reg4_dinov2.lvd142m", device
    ),
    "dinov3_b16": lambda device: timm_encoder(
        "vit_base_patch16_dinov3.lvd1689m", device
    ),
}


def frame_views(image: Image.Image) -> list[Image.Image]:
    width, height = image.size
    tile_width = width / TILE_COLUMNS
    tile_height = height * SKY_HEIGHT_FRACTION / TILE_ROWS
    tiles = [
        image.crop(
            (
                round(column * tile_width),
                round(row * tile_height),
                round((column + 1) * tile_width),
                round((row + 1) * tile_height),
            )
        )
        for row in range(TILE_ROWS)
        for column in range(TILE_COLUMNS)
    ]
    return [image, *tiles]


def embed_frames(encoder: Encoder, frames: list[Frame], device: str) -> np.ndarray:
    views_per_frame = 1 + TILE_COLUMNS * TILE_ROWS
    embeddings = []
    for start in range(0, len(frames), FRAMES_PER_BATCH):
        views = []
        for frame in frames[start : start + FRAMES_PER_BATCH]:
            with Image.open(frame.path) as image:
                views += [
                    encoder.preprocess(view)
                    for view in frame_views(image.convert("RGB"))
                ]
        with torch.inference_mode():
            encoded = normalize(
                encoder.encode(torch.stack(views).to(device)).float(), dim=-1
            )
        embeddings.append(
            encoded.cpu().numpy().reshape(-1, views_per_frame, encoded.shape[-1])
        )
    return np.concatenate(embeddings)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoders", nargs="+", choices=list(ENCODER_LOADERS))
    encoder_names = parser.parse_args().encoders
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    frames = all_frames()
    EMBEDDING_DIR.mkdir(parents=True, exist_ok=True)
    for encoder_name in encoder_names:
        embeddings = embed_frames(ENCODER_LOADERS[encoder_name](device), frames, device)
        np.save(EMBEDDING_DIR / f"{encoder_name}.npy", embeddings)
        print(f"{encoder_name}: {embeddings.shape}")


if __name__ == "__main__":
    main()
