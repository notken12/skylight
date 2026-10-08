# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Product vision, data-model rules, and scoring caveats live in AGENTS.md; follow them:

@AGENTS.md

README.md documents each score's exact formula and limitations. When you change a scoring rule, threshold, data source, or reference set, update the matching README section.

## Commands

Run everything from the repository root. Python uses `uv` (Python ≥3.12). Backend modules must be run with `python -m backend.<module>`.

```sh
uv sync
cd frontend && npm ci && npm run build && cd ..   # API server serves frontend/dist
uv run python -m backend.analysis_job              # one collector run → output/skylight.sqlite3
uv run python -m backend.analysis_job --at 2026-09-21T20:00:00Z   # historical backfill
uv run uvicorn backend.api_server:app --host 127.0.0.1 --port 8765
cd frontend && npm run dev                          # Vite dev server; proxies /api to :8765
```

Lint, type check, and tests:

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check
cd frontend && npm run check                        # tsc --noEmit
uv run python -m unittest backend/test_*.py backend/camera/test_*.py backend/phenomena/test_*.py backend/phenomena/*/test_*.py
```

Test folders have no `__init__.py`, so unittest discovery does not find them; pass the test files explicitly as above. To run one file or one test, use:

```sh
uv run python -m unittest backend/phenomena/storm/test_probsevere.py
uv run python -m unittest backend.phenomena.storm.test_probsevere.<TestClass>.<test_method>
```

A first collector run downloads the OpenCLIP `ViT-B-32` checkpoint and DWD ICON remapping data, which are cached under `output/`. A run needs network access to NOAA, DWD, and the camera providers.

## Architecture

There are two processes. They communicate only through SQLite and files under `output/`:

1. **Collector** (`backend/analysis_job.py`) is a batch job run by cron or a Coolify scheduled task. It never runs on a web request. In a live run it skips execution when a run already exists for the current UTC minute. Pipeline:
   - It fetches in parallel: the camera catalog (`camera/cameras.py`), the OpenCLIP encoder and reference scorers (`camera/view_scoring.py`), the ICON cloud volume, OVATION aurora (live runs only), and ProbSevere.
   - It builds event instances in `phenomena/`: storms from ProbSevere plus `storm/shape_complexity.py`, aurora regions from OVATION plus GFS cloud cover, sunset quality and its overlay PNG from ICON, and cloud-variation patches from ICON.
   - `camera/camera_matching.py` matches cameras to events geometrically using the circles from `phenomena/event_geometry.py`.
   - `camera/frame_archive.py` fetches and archives candidate frames. `blur_filter.py` scores sharpness, `view_scoring.py` scores OpenCLIP and warm color, and `camera_ranking.py` ranks cameras.
   - `map_data.build_map_data` assembles a single map-data dict. `weather_database.save_run` writes it in one transaction, which normalizes it into `runs`, `events`, `event_samples`, `camera_samples`, `camera_view_scores`, and related tables.
2. **API server** (`backend/api_server.py`, FastAPI) reads saved runs through `weather_queries.py`. It serves `/api/...`, `/assets` (from `output/assets`), and the built frontend. Environment variables `SKYLIGHT_DATABASE` and `SKYLIGHT_ASSETS_DIR` override the paths.

The **frontend** (`frontend/src`) is React 19 + React Router v7 + Leaflet, built with Vite. `weather-map.tsx` renders a run's map data; `types.ts` mirrors the JSON shape that `weather_queries.read_run_map` returns. If you change that shape, update the backend serializer, the queries, and `types.ts` together.

Conventions that span files:
- Network I/O goes through the helpers in `backend/weather_source.py` (`fetch_json`, `fetch_bytes`, `fetch_faa_json`, …). Scoring and parsing functions receive fetchers and scorers as callables, so tests run offline with fakes. Keep new code injectable in the same way.
- Database schema: `SCHEMA` in `weather_database.py` uses `CREATE TABLE IF NOT EXISTS`, and `initialize()` adds columns to existing databases ad hoc with `ALTER TABLE`. Any schema change needs a matching upgrade path for existing `output/skylight.sqlite3` files.
- View scores are versioned. `visual_scorer_version` includes `reference_digest()`, a hash of the reference images, so adding or relabeling images in `data/camera_view_samples` or `data/sunset_view_samples` changes the scorer version and the leave-one-out calibrated thresholds. Those folders' `manifest.json` files hold the labels; `data/interesting_view_samples` is not used by any scorer yet.
- The Docker image copies only `backend/`, the two reference-sample folders, and `frontend/dist`. A new runtime data dependency must be added to the `Dockerfile`.

`rate_limiter/` is a separate uv workspace member: a small standalone FastAPI sliding-window rate limiter (`POST /request?buckets=...`). The backend does not use it yet.
