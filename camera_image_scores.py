from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class CameraImageScores:
    warm_tone_prevalence: float


def score_camera_image(payload: bytes) -> CameraImageScores:
    with Image.open(BytesIO(payload)) as image:
        pixels = np.asarray(
            image.convert("RGB").resize((320, 240)).convert("HSV"), dtype=np.float32
        )

    hue = pixels[:, :, 0] * 360 / 255
    saturation = pixels[:, :, 1] / 255
    brightness = pixels[:, :, 2] / 255
    warm_pixels = (
        ((hue <= 55) | (hue >= 335)) & (saturation >= 0.24) & (brightness >= 0.33)
    )
    return CameraImageScores(warm_tone_prevalence=float(warm_pixels.mean()))
