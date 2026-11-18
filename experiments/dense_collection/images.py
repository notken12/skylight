from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROLLING_WIDTH = 960
ROLLING_QUALITY = 85
SHEET_COLUMNS = 6
THUMBNAIL_WIDTH = 320
CAPTION_HEIGHT = 22
SHEET_QUALITY = 85
CAPTION_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def decode(payload: bytes) -> Image.Image:
    with Image.open(BytesIO(payload)) as image:
        return image.convert("RGB")


def mean_brightness(image: Image.Image) -> float:
    return round(float(np.asarray(image.convert("L"), dtype=np.float32).mean()), 1)


def rolling_jpeg(image: Image.Image) -> bytes:
    if image.width > ROLLING_WIDTH:
        image = image.resize(
            (ROLLING_WIDTH, round(image.height * ROLLING_WIDTH / image.width)),
            Image.Resampling.LANCZOS,
        )
    encoded = BytesIO()
    image.save(encoded, "JPEG", quality=ROLLING_QUALITY)
    return encoded.getvalue()


def contact_sheet(images: list[Image.Image], captions: list[str]) -> bytes:
    thumbnails = [
        image.resize(
            (THUMBNAIL_WIDTH, round(image.height * THUMBNAIL_WIDTH / image.width))
        )
        for image in images
    ]
    cell_height = max(thumbnail.height for thumbnail in thumbnails) + CAPTION_HEIGHT
    rows = -(-len(thumbnails) // SHEET_COLUMNS)
    sheet = Image.new(
        "RGB", (SHEET_COLUMNS * THUMBNAIL_WIDTH, rows * cell_height), "white"
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(CAPTION_FONT), 15)
    for index, (thumbnail, caption) in enumerate(zip(thumbnails, captions)):
        left = index % SHEET_COLUMNS * THUMBNAIL_WIDTH
        top = index // SHEET_COLUMNS * cell_height
        draw.text((left + 4, top + 2), caption, fill="black", font=font)
        sheet.paste(thumbnail, (left, top + CAPTION_HEIGHT))
    encoded = BytesIO()
    sheet.save(encoded, "JPEG", quality=SHEET_QUALITY)
    return encoded.getvalue()
