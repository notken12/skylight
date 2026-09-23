import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from camera_matching import MatchedCamera

TEMPLATE_PATH = Path(__file__).with_name("map_template.html")


def javascript_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


def render_map(
    storms: dict[str, Any],
    cameras: list[MatchedCamera],
    metadata: dict[str, str],
    output_path: Path,
) -> None:
    html = TEMPLATE_PATH.read_text()
    html = html.replace("__STORMS__", javascript_json(storms))
    html = html.replace(
        "__CAMERAS__",
        javascript_json(
            [asdict(match.camera) | {"event_ids": match.event_ids} for match in cameras]
        ),
    )
    html = html.replace("__METADATA__", javascript_json(metadata))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
