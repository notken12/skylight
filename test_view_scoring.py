import unittest
from pathlib import Path

import torch

from camera_image_scores import CameraImageScores
from view_scoring import (
    OpenClipReferenceScorer,
    SunsetViewScorer,
    calibrated_threshold,
    leave_one_out_margins,
    reference_groups,
)


class ViewScoringTests(unittest.TestCase):
    def test_poor_storm_view_is_negative_for_view_selection(self) -> None:
        samples = [
            {"storm_presence": "storm_view", "view_quality": "good"},
            {"storm_presence": "storm_view", "view_quality": "poor"},
            {"storm_presence": "no_storm", "view_quality": "good"},
            {"storm_presence": "unknown", "view_quality": "poor"},
        ]

        self.assertEqual(reference_groups(samples), ([0], [2], [1, 3]))

    def test_leave_one_out_cutoff_separates_distinct_views(self) -> None:
        vectors = torch.tensor([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]])

        calibration = calibrated_threshold(
            leave_one_out_margins(vectors, [0, 1]), [0, 1]
        )

        self.assertEqual(calibration.true_positives, 2)
        self.assertEqual(calibration.true_negatives, 2)
        self.assertEqual(calibration.threshold, 0.0)

    def test_reference_scorer_uses_good_and_bad_examples(self) -> None:
        good = torch.tensor([[1.0, 0.0], [1.0, 0.0]])
        bad = torch.tensor([[0.0, 1.0], [0.0, 1.0]])
        scorer = OpenClipReferenceScorer(good, bad)

        accepted, rejected = scorer.score(torch.stack((good[0], bad[0])))

        self.assertTrue(accepted.accepted)
        self.assertFalse(rejected.accepted)
        self.assertEqual(accepted.good_similarity, 1.0)
        self.assertEqual(rejected.bad_similarity, 1.0)

    def test_sunset_score_adds_warm_tones_to_openclip_margin(self) -> None:
        good = torch.tensor([[1.0, 0.0], [1.0, 0.0]])
        bad = torch.tensor([[0.0, 1.0], [0.0, 1.0]])
        samples = Path(__file__).parent / "data/sunset_view_samples"
        reference_images = [
            (samples / filename).read_bytes()
            for filename in ("01-good.jpg", "03-good.jpg", "08-bad.jpg", "10-bad.jpg")
        ]
        scorer = SunsetViewScorer(
            OpenClipReferenceScorer(good, bad),
            torch.cat((good, bad)),
            reference_images,
        )

        score = scorer.score(
            torch.tensor([[0.6, 0.8]]), [CameraImageScores(warm_tone_prevalence=0.3)]
        )[0]

        self.assertAlmostEqual(score.clip_margin, -0.2)
        self.assertAlmostEqual(score.combined_score, 0.1)


if __name__ == "__main__":
    unittest.main()
