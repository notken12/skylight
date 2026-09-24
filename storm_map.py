import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from aurora import (
    MAXIMUM_CLOUD_PERCENT,
    MINIMUM_AURORA_PERCENT,
    OVATION_URL,
    classify_auroras,
)
from blur_filter import MIN_LAPLACIAN_VARIANCE
from camera_matching import match_cameras
from camera_snapshots import fetch_camera_snapshot
from cameras import load_cameras
from cloud_unusualness import load_cloud_unusualness
from event_geometry import enclosing_circle
from map_render import render_map
from probsevere import classify_storms
from shape_complexity import score_shape
from sunset_overlay import render_sunset_overlay
from sunset_weather import load_cloud_volume, load_total_cloud_cover
from view_scoring import (
    MODEL_NAME,
    MODEL_WEIGHTS,
    SUNSET_MINIMUM_SCORE,
    load_view_scorers,
    score_cameras,
)
from weather_source import (
    fetch_bytes,
    fetch_faa_json,
    fetch_json,
    fetch_text,
    parse_utc_time,
    probsevere_source,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render storms, clouds, sunsets, auroras, and public camera views on a US map."
    )
    parser.add_argument(
        "--at",
        help="Select the latest storm snapshot at or before this ISO 8601 time (UTC).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/storm_map.html"),
        help="HTML output path (default: output/storm_map.html).",
    )
    arguments = parser.parse_args()
    requested_time = parse_utc_time(arguments.at) if arguments.at else None
    map_time = requested_time or datetime.now(UTC)

    with ThreadPoolExecutor(max_workers=5) as executor:
        camera_future = executor.submit(load_cameras, fetch_json, fetch_faa_json)
        scorer_future = executor.submit(load_view_scorers)
        sunset_future = executor.submit(load_cloud_volume, map_time)
        cloud_future = executor.submit(
            load_cloud_unusualness, map_time, fetch_text, fetch_bytes
        )
        aurora_future = (
            executor.submit(fetch_json, OVATION_URL) if requested_time is None else None
        )
        source_url = probsevere_source(requested_time, fetch_text)
        weather_data = fetch_json(source_url)
        cameras = camera_future.result()
        encoder, storm_scorer, sunset_scorer = scorer_future.result()
        sunset_cloud = sunset_future.result()
        clouds = cloud_future.result()
        if aurora_future is not None:
            aurora_data = aurora_future.result()
            aurora_time = parse_utc_time(aurora_data["Forecast Time"])
            aurora_cloud = executor.submit(
                load_total_cloud_cover, aurora_time, map_time
            ).result()

    storms = classify_storms(weather_data, score_shape, enclosing_circle)
    auroras = (
        classify_auroras(aurora_data, aurora_cloud, cameras, datetime.now(UTC))
        if aurora_future is not None
        else None
    )
    matched_cameras = match_cameras(storms, cameras)
    snapshot_fetcher = partial(
        fetch_camera_snapshot,
        at=datetime.now(UTC),
        fetch_faa_json=fetch_faa_json,
        fetch_bytes=fetch_bytes,
    )
    sunset = render_sunset_overlay(map_time, sunset_cloud, cameras, arguments.output)
    scored_cameras = score_cameras(
        matched_cameras,
        sunset.camera_scores,
        snapshot_fetcher,
        encoder,
        storm_scorer,
        sunset_scorer,
    )
    calibration = storm_scorer.calibration
    sunset_calibration = sunset_scorer.calibration
    metadata = {
        "valid_time": weather_data["validTime"],
        "generated_time": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_url": source_url,
        "visual_model": f"OpenCLIP {MODEL_NAME} / {MODEL_WEIGHTS}",
        "blur_threshold": str(MIN_LAPLACIAN_VARIANCE),
        "visual_threshold": str(round(calibration.threshold, 4)),
        "storm_reference_count": str(storm_scorer.storm_count),
        "scenic_reference_count": str(storm_scorer.scenic_count),
        "poor_reference_count": str(storm_scorer.poor_count),
        "rejected_reference_count": str(
            storm_scorer.scenic_count + storm_scorer.poor_count
        ),
        "sunset_reference_count": str(sunset_scorer.good_count),
        "sunset_rejected_reference_count": str(sunset_scorer.bad_count),
        "sunset_minimum_score": str(SUNSET_MINIMUM_SCORE),
        "sunset_threshold": str(round(sunset_calibration.threshold, 4)),
        "aurora_cloud_limit": str(MAXIMUM_CLOUD_PERCENT),
        "aurora_probability_minimum": str(MINIMUM_AURORA_PERCENT),
        "sunset_validation": (
            f"{sunset_calibration.true_positives}/{sunset_calibration.positive_count} good views, "
            f"{sunset_calibration.true_negatives}/{sunset_calibration.negative_count} rejected views"
        ),
        "validation": (
            f"{calibration.true_positives}/{calibration.positive_count} storm views, "
            f"{calibration.true_negatives}/{calibration.negative_count} rejected views"
        ),
    }
    render_map(
        storms, scored_cameras, sunset, auroras, clouds, metadata, arguments.output
    )
    print(
        f"Wrote {arguments.output}: {len(storms['features'])} storms, {len(cameras)} cameras, "
        f"{len(auroras.features['features']) if auroras is not None else 0} aurora regions, "
        f"{len(clouds.features['features'])} cloud patches, "
        f"{sum(bool(camera.event_ids) for camera in auroras.cameras) if auroras is not None else 0} aurora camera candidates, "
        f"{sum(bool(camera.event_ids) for camera in scored_cameras)} candidate views, "
        f"{sum(camera.sharpness is not None and camera.sharpness < MIN_LAPLACIAN_VARIANCE for camera in scored_cameras)} blurry views, "
        f"{sum(camera.view_score is not None and camera.view_score.accepted for camera in scored_cameras)} storm views accepted, "
        f"{sum(score >= SUNSET_MINIMUM_SCORE for score in sunset.camera_scores)} sunset candidates, "
        f"{sum(camera.sunset_view_score is not None and camera.sunset_view_score.accepted for camera in scored_cameras)} sunset views accepted"
    )


if __name__ == "__main__":
    main()
