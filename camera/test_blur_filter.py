import json
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFilter

from camera.blur_filter import MIN_LAPLACIAN_VARIANCE, laplacian_variance

SAMPLES = Path(__file__).resolve().parents[1] / "data/sunset_view_samples"


class BlurFilterTests(unittest.TestCase):
    def test_saved_good_views_remain_above_threshold(self) -> None:
        samples = json.loads((SAMPLES / "manifest.json").read_text())["samples"]

        for sample in samples:
            if sample["label"] == "good":
                with self.subTest(image=sample["filename"]):
                    self.assertGreaterEqual(
                        laplacian_variance((SAMPLES / sample["filename"]).read_bytes()),
                        MIN_LAPLACIAN_VARIANCE,
                    )

    def test_blurring_a_good_view_falls_below_threshold(self) -> None:
        with Image.open(SAMPLES / "03-good.jpg") as image:
            blurred = image.filter(ImageFilter.GaussianBlur(2))
            payload = BytesIO()
            blurred.save(payload, format="PNG")

        self.assertLess(laplacian_variance(payload.getvalue()), MIN_LAPLACIAN_VARIANCE)


if __name__ == "__main__":
    unittest.main()
