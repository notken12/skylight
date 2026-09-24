from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from event_geometry import EventCircle, visual_search_circle
from shape_complexity import ShapeComplexity


def classify_storms(
    data: dict[str, Any],
    score_geometry: Callable[[dict[str, Any]], ShapeComplexity],
    extract_circle: Callable[[dict[str, Any]], EventCircle],
) -> dict[str, Any]:
    if data["product"] != "ProbSevere 3.0":
        raise ValueError(f"Expected ProbSevere 3.0, received {data['product']}")

    features = []
    for feature in data["features"]:
        models = feature["models"]
        properties = feature["properties"]
        severe_probability = int(models["probsevere"]["PROB"])
        outline_shape = score_geometry(feature["geometry"])
        event_circle = extract_circle(feature["geometry"])
        features.append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": {
                    "id": properties["ID"],
                    "valid_time": data["validTime"],
                    "circle": asdict(event_circle),
                    "view_circle": asdict(visual_search_circle(event_circle)),
                    "interestingness": {
                        "score": round(
                            (severe_probability + outline_shape.score) / 2, 1
                        ),
                        "severe_probability": severe_probability,
                        "outline_complexity": outline_shape.score,
                    },
                    "probability": severe_probability,
                    "hail_probability": int(models["probhail"]["PROB"]),
                    "wind_probability": int(models["probwind"]["PROB"]),
                    "tornado_probability": int(models["probtor"]["PROB"]),
                    "flashes_5min": int(properties["AccumFCD"]),
                    "reflectivity_dbz": float(properties["COMPREF"]),
                    "outline_shape": asdict(outline_shape),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}
