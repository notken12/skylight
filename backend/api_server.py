import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles

from backend.camera.camera_snapshots import FetchJson
from backend.camera.faa_snapshots import latest_image_at
from backend.weather_database import initialize
from backend.weather_queries import (
    camera_history,
    event_history,
    list_runs,
    read_run_map,
)
from backend.weather_source import fetch_faa_json

ROOT = Path(__file__).resolve().parents[1]


def database_path(request: Request) -> Path:
    return request.app.state.database_path


Database = Annotated[Path, Depends(database_path)]


def create_app(
    database: Path,
    assets: Path,
    frontend: Path,
    fetch_camera_json: FetchJson = fetch_faa_json,
) -> FastAPI:
    initialize(database)
    assets.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Weather phenomena and webcam views")
    app.state.database_path = database

    @app.get("/api/runs")
    def runs(
        database: Database,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        before: int | None = None,
    ) -> list[dict]:
        return list_runs(database, limit, before)

    @app.get("/api/runs/latest")
    def latest_run(database: Database) -> dict:
        latest = list_runs(database, 1)
        if not latest:
            raise HTTPException(status_code=404, detail="No saved runs")
        return latest[0]

    @app.get("/api/runs/{run_id}")
    def run_map(run_id: int, database: Database) -> dict:
        data = read_run_map(database, run_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return data

    @app.get("/api/events/{event_id}/history")
    def event_samples(event_id: int, database: Database) -> dict:
        history = event_history(database, event_id)
        if history is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return history

    @app.get("/api/cameras/history")
    def camera_samples(
        network: str,
        provider_id: str,
        database: Database,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[dict]:
        return camera_history(database, network, provider_id, limit)

    @app.get("/api/cameras/{network}/{camera_id}/latest_image")
    def latest_camera_image(
        network: str, camera_id: int, response: Response
    ) -> dict[str, str]:
        if network != "FAA WeatherCams":
            raise HTTPException(
                status_code=404, detail="Network does not require server lookup"
            )
        if camera_id <= 0:
            raise HTTPException(status_code=422, detail="Camera ID must be positive")
        images = fetch_camera_json(
            f"https://weathercams.faa.gov/api/cameras/{camera_id}/images/last/24"
        )["payload"]
        image = latest_image_at(images, datetime.now(UTC))
        if image is None:
            raise HTTPException(status_code=404, detail="No current camera image")
        response.headers["Cache-Control"] = "no-store"
        return {
            "image_url": image["imageUri"],
            "captured_at_utc": image["imageDatetime"],
        }

    app.mount("/assets", StaticFiles(directory=assets), name="assets")
    app.frontend("/", directory=frontend)
    return app


app = create_app(
    Path(os.environ.get("SKYLIGHT_DATABASE", ROOT / "output/skylight.sqlite3")),
    Path(os.environ.get("SKYLIGHT_ASSETS_DIR", ROOT / "output/assets")),
    Path(os.environ.get("SKYLIGHT_FRONTEND_DIR", ROOT / "frontend/dist")),
)
