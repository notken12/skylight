import unittest

from phenomena.event_geometry import VISUAL_CLOUD_BUFFER_KM, enclosing_circle
from phenomena.storm.probsevere import classify_storms
from phenomena.storm.shape_complexity import score_shape


class ProbSevereTests(unittest.TestCase):
    def test_storm_instance_preserves_score_inputs(self) -> None:
        ring = [
            [-100.1, 40.0],
            [-99.9, 40.0],
            [-99.9, 40.2],
            [-100.1, 40.2],
            [-100.1, 40.0],
        ]
        data = {
            "product": "ProbSevere 3.0",
            "validTime": "20260923_120000 UTC",
            "features": [
                {
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {"ID": "storm-a", "AccumFCD": "4", "COMPREF": "51.2"},
                    "models": {
                        "probsevere": {"PROB": "60"},
                        "probhail": {"PROB": "20"},
                        "probwind": {"PROB": "30"},
                        "probtor": {"PROB": "1"},
                    },
                }
            ],
        }

        instance = classify_storms(data, score_shape, enclosing_circle)["features"][0]
        properties = instance["properties"]

        self.assertEqual(properties["valid_time"], "2026-09-23T12:00:00+00:00")
        self.assertEqual(
            properties["view_circle"]["radius_km"],
            round(properties["circle"]["radius_km"] + VISUAL_CLOUD_BUFFER_KM, 1),
        )
        self.assertEqual(properties["interestingness"]["severe_probability"], 60)
        self.assertEqual(
            properties["interestingness"]["outline_complexity"],
            properties["outline_shape"]["score"],
        )
        self.assertEqual(
            properties["interestingness"]["score"],
            round((60 + properties["outline_shape"]["score"]) / 2, 1),
        )


if __name__ == "__main__":
    unittest.main()
