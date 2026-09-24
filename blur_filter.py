from io import BytesIO

import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import laplace

MIN_LAPLACIAN_VARIANCE = 30.0


def laplacian_variance(payload: bytes) -> float:
    with Image.open(BytesIO(payload)) as image:
        grayscale = ImageOps.fit(
            image.convert("L"), (320, 240), method=Image.Resampling.BILINEAR
        )
    pixels = np.asarray(grayscale, dtype=np.float32)[24:-24, 32:-32]
    return float(np.var(laplace(pixels)))
