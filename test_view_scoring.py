import unittest
from pathlib import Path

import torch

from camera_image_scores import CameraImageScores
from camera_matching import MatchedCamera
from camera_snapshots import CameraFrame, CameraSnapshot
from cameras import Camera
from view_scoring import (
    OpenClipReferenceScorer,
    PhenomenonResult,
    ScoredCamera,
    SunsetViewScore,
    SunsetViewScorer,
    ViewScore,
    calibrated_threshold,
    include_camera_frames,
    leave_one_out_margins,
    reference_groups,
    score_cameras,
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
            torch.tensor([[0.6, 0.8]]), [CameraImageScores(warm_tone_strength=0.3)]
        )[0]

        self.assertAlmostEqual(score.clip_margin, -0.2)
        self.assertAlmostEqual(score.combined_score, 0.1)

    def test_every_eligible_filter_scores_shared_camera_frame(self) -> None:
        cameras = [
            Camera("Test", name, 40.0, -100.0, f"https://example.com/{name}")
            for name in ("both", "storm", "sunset", "neither")
        ]
        matches = [
            MatchedCamera(camera, ("storm-1",) if index < 2 else ())
            for index, camera in enumerate(cameras)
        ]
        image = (
            Path(__file__).parent / "data/sunset_view_samples/03-good.jpg"
        ).read_bytes()
        fetched = []
        encoded = []
        storm_batches = []
        sunset_batches = []

        def fetch_snapshot(camera: Camera) -> CameraSnapshot:
            fetched.append(camera.name)
            return CameraSnapshot(camera, image, "2026-09-24T12:00:00Z", camera.url)

        def encode_images(images: list[bytes]) -> torch.Tensor:
            encoded.append(len(images))
            return torch.ones((len(images), 2))

        def score_storm_views(
            snapshots: list[CameraSnapshot], vectors: torch.Tensor
        ) -> list[ViewScore]:
            storm_batches.append([snapshot.camera.name for snapshot in snapshots])
            self.assertEqual(len(vectors), 2)
            return [
                ViewScore(
                    0.5,
                    0.3,
                    0.2,
                    0.1,
                    margin,
                    0.1,
                    visible,
                    snapshot.captured_at,
                    snapshot.image_url,
                )
                for snapshot, margin, visible in zip(
                    snapshots, (0.2, -0.1), (True, False), strict=True
                )
            ]

        def score_sunset_views(
            vectors: torch.Tensor, image_scores: list[CameraImageScores]
        ) -> list[SunsetViewScore]:
            sunset_batches.append(len(image_scores))
            self.assertEqual(len(vectors), 2)
            return [
                SunsetViewScore(0.6, 0.2, 0.4, score, 0.1, visible)
                for score, visible in ((0.5, True), (0.0, False))
            ]

        scored = score_cameras(
            matches,
            (10, 0, 10, 0),
            {3},
            fetch_snapshot,
            encode_images,
            score_storm_views,
            score_sunset_views,
        )

        self.assertCountEqual(fetched, ["both", "storm", "sunset", "neither"])
        self.assertEqual(encoded, [3])
        self.assertEqual(storm_batches, [["both", "storm"]])
        self.assertEqual(sunset_batches, [2])
        self.assertEqual(
            scored[0].phenomena,
            {
                "storm": PhenomenonResult(score=0.2, visible=True),
                "sunset": PhenomenonResult(score=0.5, visible=True),
            },
        )
        self.assertEqual(
            scored[1].phenomena,
            {"storm": PhenomenonResult(score=-0.1, visible=False)},
        )
        self.assertEqual(
            scored[2].phenomena,
            {"sunset": PhenomenonResult(score=0.0, visible=False)},
        )
        self.assertEqual(scored[3].phenomena, {})
        self.assertIsNotNone(scored[3].sharpness)
        self.assertIsNotNone(scored[3].frame)

    def test_site_directions_and_aurora_candidates_get_frames(self) -> None:
        cameras = [
            Camera("FAA WeatherCams", "North", 40, -100, "https://example.com/north"),
            Camera("FAA WeatherCams", "South", 40, -100, "https://example.com/south"),
            Camera("FAA WeatherCams", "Other", 41, -100, "https://example.com/other"),
            Camera("USGS HIVIS", "Aurora", 60, -150, "https://example.com/aurora"),
        ]
        existing = CameraFrame("https://example.com/north.jpg", "2026-09-25T12:00Z")
        scored = [
            ScoredCamera(
                camera, (), None, None, existing if index == 0 else None, None, None
            )
            for index, camera in enumerate(cameras)
        ]
        fetched = []

        def fetch_frame(camera: Camera) -> CameraFrame:
            fetched.append(camera.name)
            return CameraFrame(f"{camera.url}.jpg", "2026-09-25T12:01Z")

        with_frames = include_camera_frames(scored, {3}, fetch_frame)

        self.assertCountEqual(fetched, ["South", "Aurora"])
        self.assertEqual(with_frames[0].frame, existing)
        assert with_frames[1].frame is not None
        self.assertEqual(
            with_frames[1].frame.image_url, "https://example.com/south.jpg"
        )
        self.assertIsNone(with_frames[2].frame)
        assert with_frames[3].frame is not None
        self.assertEqual(
            with_frames[3].frame.image_url, "https://example.com/aurora.jpg"
        )
        self.assertIsNone(scored[1].frame)


if __name__ == "__main__":
    unittest.main()
