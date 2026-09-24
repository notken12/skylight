import unittest
from io import BytesIO

from PIL import Image

from camera_image_scores import score_camera_image


def image_bytes(
    upper_color: tuple[int, int, int], lower_color: tuple[int, int, int]
) -> bytes:
    image = Image.new("RGB", (320, 240), lower_color)
    image.paste(upper_color, (0, 0, 320, 168))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class CameraImageScoreTests(unittest.TestCase):
    def test_warm_pixels_count_across_the_whole_frame(self) -> None:
        orange = (255, 120, 0)
        blue = (0, 100, 255)

        warm_upper = score_camera_image(image_bytes(orange, blue))
        warm_lower = score_camera_image(image_bytes(blue, orange))

        self.assertAlmostEqual(warm_upper.warm_tone_prevalence, 0.7)
        self.assertAlmostEqual(warm_lower.warm_tone_prevalence, 0.3)

    def test_warm_pixels_at_the_frame_edge_count(self) -> None:
        image = Image.new("RGB", (320, 240), (0, 100, 255))
        image.paste((255, 120, 0), (0, 0, 16, 240))
        output = BytesIO()
        image.save(output, format="PNG")

        score = score_camera_image(output.getvalue())

        self.assertAlmostEqual(score.warm_tone_prevalence, 0.05)


if __name__ == "__main__":
    unittest.main()
