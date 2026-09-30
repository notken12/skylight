import unittest
from unittest.mock import Mock

from camera.camera_matching import MatchedCamera
from camera.camera_ranking import rank_cameras
from camera.cameras import linked_aurora_cameras
from camera.view_scoring import include_camera_frames, score_cameras
from phenomena.aurora.aurora import AuroraCamera, AuroraEvents
from phenomena.sunset.sunset_overlay import SunsetOverlay


class LinkedAuroraCameraTests(unittest.TestCase):
    def test_linked_feeds_do_not_request_or_score_still_frames(self) -> None:
        cameras = linked_aurora_cameras()
        self.assertEqual(len(cameras), 4)
        self.assertTrue(all(camera.link_only for camera in cameras))
        self.assertFalse(cameras[-1].feed_verified)

        fetch_snapshot = Mock(side_effect=AssertionError("unexpected snapshot"))
        fetch_frame = Mock(side_effect=AssertionError("unexpected frame"))
        encode_images = Mock(side_effect=AssertionError("unexpected encoding"))
        score_storm_views = Mock(side_effect=AssertionError("unexpected storm score"))
        score_sunset_views = Mock(side_effect=AssertionError("unexpected sunset score"))
        scored = score_cameras(
            [MatchedCamera(camera, ()) for camera in cameras],
            (0, 0, 0, 0),
            set(range(4)),
            fetch_snapshot,
            encode_images,
            score_storm_views,
            score_sunset_views,
        )
        with_frames = include_camera_frames(scored, set(range(4)), fetch_frame)

        self.assertTrue(all(camera.frame is None for camera in with_frames))
        self.assertTrue(all(camera.sharpness is None for camera in with_frames))
        fetch_snapshot.assert_not_called()
        fetch_frame.assert_not_called()

        auroras = AuroraEvents(
            features={
                "features": [
                    {"properties": {"id": "aurora-a", "interestingness": {"score": 70}}}
                ]
            },
            cameras=tuple(AuroraCamera(("aurora-a",), 20, True) for _ in cameras),
            observation_time="now",
            forecast_time="now",
            cloud_time="now",
            cloud_source_url="source",
        )
        sunset = SunsetOverlay(
            "now", "now", "source", "band", "quality", (False,) * 4, (0,) * 4
        )
        self.assertEqual(
            rank_cameras(with_frames, {"features": []}, sunset, auroras),
            (None,) * 4,
        )


if __name__ == "__main__":
    unittest.main()
