from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class CameraImageScores:
    warm_tone_strength: float


def score_camera_image(payload: bytes) -> CameraImageScores:
    with Image.open(BytesIO(payload)) as image:
        pixels = np.asarray(
            image.convert("RGB").resize((320, 240)).convert("HSV"), dtype=np.float32
        )

    hue = pixels[:, :, 0] * 360 / 255
    saturation = pixels[:, :, 1] / 255
    brightness = pixels[:, :, 2] / 255
    hue_weight = np.interp(
        hue,
        (0, 15, 35, 55, 80, 300, 320, 340, 360),
        (1, 1, 0.95, 0.7, 0, 0, 0.35, 0.9, 1),
    )
    warm_color = hue_weight * saturation**1.5 * brightness
    return CameraImageScores(warm_tone_strength=float(np.sqrt(np.mean(warm_color**2))))
