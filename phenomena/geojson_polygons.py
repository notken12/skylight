from typing import Any


def polygons_of(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        raise ValueError(
            f"Expected Polygon or MultiPolygon, received {geometry['type']}"
        )
    if not polygons:
        raise ValueError("Shape must contain at least one polygon")
    return polygons
