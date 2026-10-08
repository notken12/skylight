# Skylight app

The user-facing web app. The debug map in `../frontend` stays as a developer tool.

Two modes, switched from the bar at the bottom:

- **Explore**: a MapLibre globe that flattens into a map as you zoom. Events with a camera view are white pills showing the phenomenon symbol and the number of views; nearby ones of the same kind merge. Events nobody can see are small faded dots. Selecting an event opens a side card (desktop) or bottom sheet (phone) with its coordinates and camera frames.
- **Watch**: full-screen camera frames that advance every 12 seconds, best-ranked first. Arrow keys step through them and the space bar pauses.

## Run it

```sh
npm ci
npm run dev        # http://127.0.0.1:5173, proxies /api and /assets to the API server on :8765
npm run check      # type check
npm run build      # static files in dist/
```

The API server (`uv run uvicorn backend.api_server:app --port 8765` from the repository root) must have at least one saved run. To have the API server serve this app's build instead of the developer map locally, set `SKYLIGHT_FRONTEND_DIR=deployment_frontend/dist`; the [root README](../README.md#frontends) covers switching between the two frontends. The Docker image builds this app and serves it from `/app/frontend/dist` without an environment override.

The API server does not need PyTorch, which only the collector uses for image scoring. On a machine where `uv sync` cannot install the pinned PyTorch (Intel Macs, for example), start it with just its runtime packages:

```sh
uv run --no-project --with fastapi --with uvicorn --with numpy --with scipy --with pyproj \
  --with eccodes --with eccodeslib --with netcdf4 --with pillow \
  uvicorn backend.api_server:app --host 127.0.0.1 --port 8765
```

## Known issue: shared camera views

Several nearby storms often list the same cameras, so their panels show identical frames. This comes from the backend's camera matching, and the fix belongs there; see [Known issue: one camera matched to several storms](../README.md#known-issue-one-camera-matched-to-several-storms). The app shows the matches as they are.

## Layout

- `src/core/`: plain TypeScript with no React or DOM: API calls, the JSON types, and `sky.ts`, which turns a saved run into events and camera views. A future native app can reuse it.
- `src/components/`: the map (`sky-map.tsx`), mode bar, and phenomenon symbols.
- `src/routes/`: `root.tsx` loads the latest run and keeps the map mounted; `explore.tsx` and `watch.tsx` are the two modes.

What counts as a camera view: a camera whose frame passed the storm image filter for a matched storm, or a forecast aurora candidate. Sunsets are left out until that mode exists. Cloud patterns show only the 10 most varied tiles. Base map tiles come from [OpenFreeMap](https://openfreemap.org/) (Positron style), recoloured to white land and pale water. Country borders are thin ink on the globe and ease to light grey when zoomed in. `public/coastline.geojson` is the public-domain [Natural Earth](https://www.naturalearthdata.com/) 1:50m coastline, simplified (about 2 km tolerance, islets under 0.15° dropped, coordinates rounded to 0.01°); it draws an ink coastline on the globe and fades out by zoom 5.5, where the base map's own shoreline takes over. The base style has no coastline layer, and outlining its tiled water would draw tile seams.
