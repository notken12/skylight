import unittest

from camera.camera_ranking import rank_cameras
from camera.cameras import Camera
from camera.view_scoring import ScoredCamera, SunsetViewScore, ViewScore
from phenomena.aurora.aurora import AuroraCamera, AuroraEvents
from phenomena.sunset.sunset_overlay import SunsetOverlay


class CameraRankingTests(unittest.TestCase):
    def test_weighted_sum_uses_view_and_strongest_matched_event(self) -> None:
        cameras = [
            ScoredCamera(
                Camera("Test", "Both", 40, -100, "https://example.com/both"),
                ("storm-a", "storm-b"),
                ViewScore(0, 0, 0, 0, 0.2, 0.06, True, "now", "image"),
                SunsetViewScore(0, 0, 0, 0.3, 0.06, True),
                None,
                120,
                None,
            ),
            ScoredCamera(
                Camera("Test", "Storm", 41, -101, "https://example.com/storm"),
                ("storm-a",),
                ViewScore(0, 0, 0, 0, 0.1, 0.06, True, "now", "image"),
                None,
                None,
                60,
                None,
            ),
            ScoredCamera(
                Camera("Test", "Aurora", 60, -150, "https://example.com/aurora"),
                (),
                None,
                None,
                None,
                10,
                None,
            ),
        ]
        storms = {
            "features": [
                {"properties": {"id": "storm-a", "interestingness": {"score": 30}}},
                {"properties": {"id": "storm-b", "interestingness": {"score": 50}}},
            ]
        }
        sunset = SunsetOverlay(
            "now", "now", "source", "band", "quality", (True, False, False), (80, 0, 0)
        )
        auroras = AuroraEvents(
            features={
                "features": [
                    {"properties": {"id": "aurora-a", "interestingness": {"score": 70}}}
                ]
            },
            cameras=(
                AuroraCamera((), None, False),
                AuroraCamera((), None, False),
                AuroraCamera(("aurora-a",), 20, True),
            ),
            observation_time="now",
            forecast_time="now",
            cloud_time="now",
            cloud_source_url="source",
        )

        both, storm, aurora = rank_cameras(cameras, storms, sunset, auroras)

        assert both is not None
        assert storm is not None
        assert aurora is not None
        self.assertEqual(both.score, 157.6)
        self.assertEqual(both.components["storm"].weighted_score, 64)
        self.assertEqual(both.components["sunset"].weighted_score, 73.6)
        self.assertEqual(both.sharpness_contribution, 20)
        self.assertEqual(storm.score, 43.6)
        self.assertEqual(aurora.score, 60.8)
        self.assertEqual(aurora.sharpness_contribution, 0)


if __name__ == "__main__":
    unittest.main()
