import random
import tarfile
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from experiments.dense_collection.dense_pass import recent_processed_urls
from experiments.dense_collection.frame_sources import (
    CameraSource,
    Frame,
    still_frames,
)
from experiments.dense_collection.labels import is_valid_label
from experiments.dense_collection.r2 import TarShardWriter
from experiments.dense_collection.selection import (
    audit_choices,
    label_selection,
    may_have_daylit_frames,
    new_daylit_frames,
)

DENVER = (39.74, -104.99)
NOON_DENVER = "2026-06-21T19:00:00+00:00"
MIDNIGHT_DENVER = "2026-06-21T07:00:00+00:00"

COMPLETE_LABEL = {
    "type": "lenticular",
    "confidence": "low",
    "sky": "A lens-shaped cloud over a ridge.",
    "sky_share": "most",
    "cloud_cover": "few",
    "low_cloud": False,
    "mid_cloud": True,
    "high_cloud": False,
    "wave_texture": True,
    "cap_cloud": False,
    "convection": "none",
    "precipitation": False,
    "obstruction": "none",
}


def frame(key: str, captured_at: str) -> Frame:
    return Frame(key, key, key, captured_at, None)


class LabelSelectionTests(unittest.TestCase):
    def test_gate_takes_highest_scores_and_random_slice_records_probability(
        self,
    ) -> None:
        scores = [index / 100 for index in range(100)]
        selections = label_selection(scores, budget=20, rng=random.Random(1))
        gate = [index for index, pick in enumerate(selections) if pick.kind == "gate"]
        drawn = [
            index for index, pick in enumerate(selections) if pick.kind == "random"
        ]
        self.assertEqual(gate, list(range(83, 100)))
        self.assertEqual(len(drawn), 3)
        self.assertTrue(all(index < 83 for index in drawn))
        self.assertTrue(all(selections[index].probability == 1.0 for index in gate))
        self.assertTrue(
            all(selection.probability == 3 / 83 for selection in selections[:83])
        )
        self.assertEqual(
            sum(1 for selection in selections if not selection.kind), 100 - 20
        )

    def test_fewer_frames_than_gate_share_are_all_gate_picks(self) -> None:
        selections = label_selection([0.2, 0.9, 0.5], budget=112, rng=random.Random(1))
        self.assertEqual([selection.kind for selection in selections], ["gate"] * 3)

    def test_no_frames_select_nothing(self) -> None:
        self.assertEqual(label_selection([], budget=112, rng=random.Random(1)), [])


class FrameFilterTests(unittest.TestCase):
    def test_skips_processed_urls_and_frames_without_sun(self) -> None:
        frames = [
            frame("night", MIDNIGHT_DENVER),
            frame("seen", NOON_DENVER),
            frame("later", "2026-06-21T19:10:00+00:00"),
            frame("new", NOON_DENVER),
        ]
        kept = new_daylit_frames(frames, {"seen"}, *DENVER)
        self.assertEqual([kept_frame.key for kept_frame, _ in kept], ["new", "later"])
        self.assertTrue(all(elevation > 60 for _, elevation in kept))

    def test_camera_without_sun_in_history_window_is_skipped(self) -> None:
        at_night = datetime.fromisoformat(MIDNIGHT_DENVER)
        just_after_sunset = datetime(2026, 6, 22, 4, 0, tzinfo=UTC)
        self.assertFalse(may_have_daylit_frames(at_night, *DENVER))
        self.assertTrue(may_have_daylit_frames(just_after_sunset, *DENVER))

    def test_processed_urls_older_than_a_day_are_forgotten(self) -> None:
        entries = {
            "old": "2026-06-19T12:00:00+00:00",
            "recent": "2026-06-21T11:00:00+00:00",
        }
        at = datetime.fromisoformat("2026-06-21T12:00:00+00:00")
        self.assertEqual(list(recent_processed_urls(entries, at)), ["recent"])


class StillFrameTests(unittest.TestCase):
    def test_frames_are_keyed_by_capture_time_not_by_url(self) -> None:
        camera = CameraSource(
            "caltrans",
            "mammoth",
            *DENVER,
            ["https://x/now.jpg", "https://x/previous-1.jpg", "https://x/copy.jpg"],
        )
        modified = {
            "https://x/now.jpg": "Sun, 21 Jun 2026 19:00:00 GMT",
            "https://x/previous-1.jpg": "Sun, 21 Jun 2026 18:00:00 GMT",
            "https://x/copy.jpg": "Sun, 21 Jun 2026 18:00:00 GMT",
        }
        frames = still_frames(camera, lambda url: {"last-modified": modified[url]})
        self.assertEqual(
            [(frame.key, frame.filename) for frame in frames],
            [
                ("caltrans:mammoth@2026-06-21T19:00:00+00:00", "20260621T190000Z.jpg"),
                ("caltrans:mammoth@2026-06-21T18:00:00+00:00", "20260621T180000Z.jpg"),
            ],
        )
        self.assertEqual(frames[1].image_url, "https://x/copy.jpg")


class AuditChoiceTests(unittest.TestCase):
    def test_flagged_windows_always_chosen_and_random_fill_the_rest(self) -> None:
        windows = [str(index) for index in range(10)]
        choices = audit_choices(windows, {"3"}, 4, random.Random(2))
        self.assertEqual(choices["3"].reason, "flagged")
        self.assertEqual(choices["3"].probability, 1.0)
        drawn = [
            window for window, choice in choices.items() if choice.reason == "random"
        ]
        self.assertEqual(len(drawn), 3)
        self.assertNotIn("3", drawn)
        self.assertTrue(all(choices[window].probability == 3 / 9 for window in drawn))

    def test_many_flagged_windows_leave_no_random_draws(self) -> None:
        choices = audit_choices(["1", "2", "3"], {"1", "2", "3"}, 2, random.Random(2))
        self.assertEqual({choice.reason for choice in choices.values()}, {"flagged"})


class LabelValidationTests(unittest.TestCase):
    def test_accepts_complete_label(self) -> None:
        self.assertTrue(is_valid_label(COMPLETE_LABEL))

    def test_rejects_missing_extra_or_mistyped_fields(self) -> None:
        self.assertFalse(is_valid_label(COMPLETE_LABEL | {"extra": 1}))
        self.assertFalse(is_valid_label(COMPLETE_LABEL | {"low_cloud": "false"}))
        self.assertFalse(is_valid_label(COMPLETE_LABEL | {"cloud_cover": "most"}))
        self.assertFalse(
            is_valid_label(
                {key: COMPLETE_LABEL[key] for key in COMPLETE_LABEL if key != "sky"}
            )
        )


class TarShardWriterTests(unittest.TestCase):
    def test_starts_a_new_shard_once_one_is_full_and_uploads_each(self) -> None:
        uploaded: dict[str, list[str]] = {}

        def upload(key: str, path: Path) -> None:
            with tarfile.open(path) as archive:
                uploaded[key] = archive.getnames()

        with tempfile.TemporaryDirectory() as directory:
            writer = TarShardWriter(Path(directory), "rolling/pass", upload, 5_000)
            keys = [writer.add(f"frame_{index}", b"x" * 3_000) for index in range(3)]
            writer.close()
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(
            keys,
            ["rolling/pass/000.tar", "rolling/pass/000.tar", "rolling/pass/001.tar"],
        )
        self.assertEqual(
            uploaded,
            {
                "rolling/pass/000.tar": ["frame_0", "frame_1"],
                "rolling/pass/001.tar": ["frame_2"],
            },
        )


if __name__ == "__main__":
    unittest.main()
