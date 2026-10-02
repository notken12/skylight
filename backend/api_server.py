import sqlite3
import os
from pathlib import Path
from typing import Annotated, List

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.staticfiles import StaticFiles

from backend.weather_database import initialize
from backend.weather_queries import (
    camera_history,
    event_history,
    list_runs,
    read_run_map,
)
from backend.camera.cameras import CameraDatabase, get_camera_database
from backend.rate_limiter_client import RateLimiterClient
import boto3
from backend.camera.archive.archive_service import (
    CameraArchiveService,
    WebpImageConverter,
)

ROOT = Path(__file__).resolve().parents[1]


def database_path(request: Request) -> Path:
    return request.app.state.database_path


Database = Annotated[Path, Depends(database_path)]


def get_real_ip(request: Request) -> str | None:
    # 1. Check the X-Forwarded-For header (often a comma-separated list: client, proxy1, proxy2)
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # The first IP in the list is the original client
        client_ip = x_forwarded_for.split(",")[0].strip()
    else:
        # 2. Fallback to X-Real-IP or direct client host
        client_ip = request.headers.get("X-Real-IP") or (
            request.client.host if request.client else None
        )
    return client_ip


def create_app(
    database: Path,
    assets: Path,
    frontend: Path,
    camera_database: CameraDatabase,
    rate_limiter_client: RateLimiterClient,
    camera_archive_service: CameraArchiveService,
) -> FastAPI:
    initialize(database)
    assets.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Weather phenomena and webcam views")
    app.state.database_path = database

    def rate_limit(buckets: List[str]):
        ok = rate_limiter_client.request(buckets)
        if not ok:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)

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

    @app.post("/api/cameras/{network}/{camera_id}/archive")
    def archive_frame(network: str, camera_id: str, req: Request):
        ip = get_real_ip(req)
        if not ip:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        rate_limit(["global", f"ip:{ip}"])
        img = camera_database.fetch_latest_snapshot(network, camera_id).image
        id = camera_archive_service.archive_frame(network, camera_id, img)
        return id

    app.mount("/assets", StaticFiles(directory=assets), name="assets")
    app.frontend("/", directory=frontend)
    return app


database = Path(os.environ.get("SKYLIGHT_DATABASE", ROOT / "output/skylight.sqlite3"))
s3_client = boto3.client("s3")
with sqlite3.connect(database) as db_connection:
    camera_archive_service = CameraArchiveService(
        s3=s3_client,
        db_connection=db_connection,
        bucket="skylight",
        image_converter=WebpImageConverter(),
    )
    app = create_app(
        database=database,
        assets=Path(os.environ.get("SKYLIGHT_ASSETS_DIR", ROOT / "output/assets")),
        frontend=ROOT / "frontend/dist",
        camera_database=get_camera_database(),
        rate_limiter_client=RateLimiterClient(
            os.environ.get("RATE_LIMITER_PATH", "http://localhost:8001/request")
        ),
        camera_archive_service=camera_archive_service,
    )
