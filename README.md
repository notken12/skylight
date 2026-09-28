# Skylight weather map

## 3D cloud variation heatmap

The map shows a toggleable experimental cloud layer over the contiguous US and lists its eight highest-scoring patches. Each 1.5° tile receives a score based only on variation in the same [DWD ICON cloud-fraction forecast](https://opendata.dwd.de/weather/nwp/icon/grib/) used by the sunset layer. The scorer averages the absolute change between neighboring cells in the two horizontal directions and adds the mean change between altitude layers. The popup shows those two components and the mean peak cloud fraction in each column for context; cloud amount does not affect the score.

Clear or uniform volumes score zero. Other tiles receive a 0–100 percentile among the varying tiles in the same forecast. This is **not historical rarity**, a cloud-type classification, or a probability of a good camera view. The remapped 0.25° horizontal grid and 0.5 km altitude steps represent broad forecast structure, not the geometry of individual cloud elements. The horizontal and vertical components are changes per sampled grid step, so they are not directly comparable as physical gradients per kilometre. Compare high-ranked patches against observed satellite imagery and camera frames before treating them as visually unusual.

## Aurora regions

The current map also reads the [NOAA SWPC OVATION 30-minute aurora forecast](https://www.swpc.noaa.gov/products/aurora-30-minute-forecast) and NOAA GFS instantaneous total cloud cover. It groups 1° forecast cells into compact 4° regions when OVATION gives at least 20% aurora probability, GFS cloud cover is at most 30%, and the sun is at least 6° below the horizon at the forecast time. Each region retains its qualifying cells as a footprint and gets an enclosing search circle. The existing camera matcher finds candidate views; a camera is highlighted with a purple outline only when it is known to capture the night sky, its own cloud-cover forecast is at most 30%, and it is dark at the camera. Aviation cameras do not qualify for aurora matches. Aurora interestingness is the region's peak OVATION probability discounted by its mean forecast cloud cover. These are forecast-based candidate views, not image-confirmed auroras.

The initial cloud request covers 35–80°N and 180–310°E, spanning the current US and Canadian camera catalog. Aurora regions appear only for current maps because the OVATION endpoint serves the latest forecast. Historical `--at` maps show no aurora regions. The map displays the OVATION and GFS valid times and source links. GFS cloud cover is a forecast, not a detected or camera-observed percentage, and a search circle only approximates the visibility area.

Night-sky still-image sources include the [University of Calgary TREx RGB network](https://data.phys.ucalgary.ca/data/datasets/trex_rgb.html) and [AuroraMAX in Yellowknife](https://auroramax.com/live). The [Calgary real-time API](https://data.phys.ucalgary.ca/data/realtime.html) supplies TREx images and stream update times; AuroraMAX supplies a latest JPEG and its HTTP modification time. Only feeds updated within the past hour enter the camera catalog. These sky-facing cameras are matched spatially without a compass bearing. Their existing still-image preview and sharpness path is reused, but the storm and sunset image classifiers are not aurora detectors.

The [Churchill Northern Lights Cam](https://explore.org/livecams/polar-bears/northern-lights-cam) and University of Alaska's [Poker Flat](https://allsky.gi.alaska.edu/poker-flat) and [Toolik Lake](https://allsky.gi.alaska.edu/toolik-lake) live views are also on the map. They link to external streams; Skylight has no verified still-frame time for them, so it does not fetch a preview, run image scoring, or place them in the scored-camera ranking. The [Athabasca University all-sky camera](https://autumn.athabascau.ca/auroracamhd.htm) is listed as an unverified feed because its site was unreachable on September 26, 2026; it cannot become a highlighted aurora candidate until the feed is verified. The University of Alaska's Gakona page describes that camera as incoming, so it is not listed as a live camera.

## Sunset overlay

The main `storm_map.py` command also draws the sunset band and quality layer. The band covers locations where the sun is between 2° above and 6° below the horizon after solar noon. Inside the continental US portion of that band, a colored 0–100 experimental quality estimate uses live [DWD ICON global cloud forecasts](https://opendata.dwd.de/weather/nwp/icon/grib/). Cameras with a forecast score below 10 are dimmed unless they independently qualify as storm views. Cameras scoring at least 10 are checked with a combined image score: the OpenCLIP good-minus-rejected similarity margin plus warm-color strength across the entire frame. A camera with any visible phenomenon keeps its network color; a visible sunset gets a yellow outline. Storm or sunset candidates with no visible phenomena show an X. The lower gate allows a confirmed vivid sunset at McClure Mountain, previously scored 12/100 under GFS, to reach the image filter. The sunset candidate list includes cameras with any visible phenomenon and ranks them by sunset score, including cameras whose storm filter alone accepted the frame. Hover or click for the frame, forecast score, image score, live feed link, and any storm match details. When several FAA cameras share one location, click the site dot to choose a direction and see that camera's details. Layer controls let you show or hide the band, quality colors, and sunset cameras independently.

The scorer follows the **two phases described in the [SunsetHue whitepaper](https://sunsethue.com/whitepaper)**: trace sunlight through the 3D cloud field to estimate each cell's reflection potential, then trace multiple sight lines from an observer and average their visible reflection. It uses ICON cloud fraction on 50 selected model levels from the lower atmosphere through roughly 17 km, including every model level from 56 through 90 to retain closely spaced upper clouds, with matching half-level heights to locate each layer. DWD's [official nearest-neighbor weights](https://opendata.dwd.de/weather/lib/cdo/) map the native triangular grid to 0.25°; the cloud fields are then interpolated onto 0.5 km altitude layers. Middle and high clouds receive more weight. [SunsetHue reports switching from GFS to ICON](https://sunsethue.com/news/new-model-icon), but does not publish its exact ray sampling, weights, post-processing formulas, or selected ICON fields. Our numbers are **not** its quality metric and are not calibrated probabilities. This version does not apply the whitepaper's humidity and golden-hour duration adjustments.

Cloud data priorities for the next iteration:

1. **NOAA HRRR native-level cloud fraction and cloud ice/water fields** over the US for finer 3D cloud geometry and short-range forecasts. Its native-level inventory includes fraction of cloud cover, height, cloud water, and cloud ice by hybrid level; this is more useful for ray tracing than only low/mid/high summaries. [NOAA HRRR product inventory](https://www.nco.ncep.noaa.gov/pmb/products/hrrr/).
2. **GOES-East/West ABI observations** to correct forecast cloud placement and protect high, thin cirrus. The 1.38 µm Band 4 is specifically sensitive to very thin cirrus in daylight; cloud-top height, cloud phase/type, cloud-cover layers, and optical depth add height and translucency information. Near and after sunset Band 4 loses reflected sunlight, so pair it with infrared cloud products rather than treating a dark Band 4 pixel as clear sky. [GOES-R instrument requirements](https://goes-r.noaa.gov/syseng/docs/MRD.pdf), [NOAA cloud products](https://www.star.nesdis.noaa.gov/goesr/product_cp_cloud.php).
3. **Surface humidity, visibility, aerosol/smoke, and more webcam validation** for local visibility and calibration. The forecast score does not use these; webcam frames currently feed only the separate OpenCLIP view filter. The satellite products provide cloud tops and inferred layers, not a complete measured 3D cloud volume; passive satellite views can miss clouds beneath upper layers. [NOAA cloud product research](https://repository.library.noaa.gov/view/noaa/54226/noaa_54226_DS1.pdf).

The ICON layer is a forecast, not a live observation. Even with closely spaced upper layers, thin cirrus may be absent from its modeled cloud fraction or lost in horizontal remapping. The sunset image filter compares seventeen user-selected good frames with nine user-selected bad frames and all thirteen rejected storm-view references. Its full-frame combined score cutoff is 0.1116; choosing that cutoff on leave-one-out scores accepts fifteen of seventeen good frames and rejects all twenty-two bad frames. These are exploratory in-sample results, not an independent validation set. The fixed reference images and original URLs are in `data/sunset_view_samples/manifest.json`. A camera's presence in the band alone does not establish its field of view or image quality for sunset. The McClure Mountain frame was a known counterexample to the previous GFS forecast score: its high clouds produced only 12/100. ICON scores require validation against saved frames before treating the 0–100 heatmap as calibrated.

The September 25 Reno/Tahoe frames expose a forecast-scoring failure. ICON's 02:00 UTC forecast contained 94–100% cloud cover around 10.5–11 km near Reno, extending to 11.5 km, yet the 02:06 UTC map assigned the nearby cameras only 7–15/100 despite their vivid pink clouds. The current ray marcher treats cloud-cover fraction as light extinction even though DWD provides separate cloud-ice content (`QI`), samples viewing angles only through 35° above the horizon, and starts those rays at sea level. It also fails to block sunlight when a solar ray passes below terrain or the horizon: at 02:18 UTC it assigns full reflection potential to local 11 km clouds with the sun about 5.5° below the horizon. These limitations need correction and validation before using this score to rank high-cloud sunsets.

A Python collector saves NOAA ProbSevere v3 storm objects, aurora regions, cloud patches, sunset forecasts, and public webcam views in SQLite. A FastAPI server exposes saved runs to a React Router v7 map. Storm polygon fill represents the modeled chance that a storm will produce **any severe hazard in the next 60 minutes**. It is not an observed intensity or an official warning. Dashed circles show estimated visual search areas; bright network-colored camera dots have at least one visible phenomenon or meet the aurora forecast criteria, X markers are storm or sunset candidates with none, and cameras without a candidate view are translucent in their network color.

## Run

```sh
uv sync
cd frontend && npm ci && npm run build && cd ..
uv run python storm_map.py
uv run uvicorn api_server:app --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765/>. The collector writes `output/skylight.sqlite3`, saves immutable sunset overlays in `output/assets`, and archives fetched candidate frames under `output/assets/frames`. The page loads the latest run, lets you select earlier runs, and links event popups to their score histories. OpenStreetMap tiles require an HTTP page with a valid Referer.

### Coolify

Deploy the repository as a Dockerfile application. Set the exposed port to `8765` and mount persistent storage at `/app/output`. The image serves the built frontend and API; its collector uses the same database and assets. The container runs as UID `10001`, so a host directory mount must be writable by that UID. Keep one application replica while using the local SQLite database.

Add a Coolify Scheduled Task to the application with command `cd /app && /app/.venv/bin/python storm_map.py` and an initial frequency of `*/30 * * * *`. Choose a timeout based on an observed run rather than the five-minute default. Run the task once with **Execute Now** and verify the saved run appears on the map. The collector currently skips duplicate UTC-minute slots but does not prevent executions from overlapping across different minutes.

The image retains its Python dependencies and reference images; `/app/output` retains the SQLite database, scored frames, overlays, ICON cache, and model cache across deployments. Back up the database consistently along with the saved assets. The Linux PyTorch dependencies in the current lockfile include CUDA libraries, so allow substantial build disk space even on a CPU-only host.

The collector can be scheduled, for example every fifteen minutes:

```cron
*/15 * * * * cd /Users/ken/dev/skylight && /Users/ken/.local/bin/uv run python storm_map.py
```

Each successful run is committed as one SQLite transaction. A rerun in the same UTC minute is skipped. The API offers `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/events/{id}/history`, and `GET /api/cameras/history?network=...&provider_id=...`. The FastAPI server serves the built frontend and saved assets; it never runs the collector on a page request. For frontend development, run `npm run dev` inside `frontend` and keep the API server on port 8765.

The first run downloads the OpenCLIP `ViT-B-32` `laion2b_s34b_b79k` checkpoint. For sunset, it also downloads DWD's 0.25° ICON remapping weights and static model-level heights, then caches the US subset under `output/icon_cache`. Each run downloads 50 current ICON cloud-level files; aurora still uses GFS total cloud cover. The map samples sunset forecast quality at each camera and fetches recent frames for storm candidates and sunset cameras scoring at least 10. Each fetched frame gets a phenomenon-independent warm-color strength score. Hue weights taper across red, orange, yellow, and pink without hard saturation or brightness cutoffs. Per-pixel strength multiplies hue weight, saturation to the power 1.5, and brightness; the root mean square across the entire 320 × 240 image gives small vivid patches more influence than an area average. This 0–1 value is a color score, not a percentage of warm pixels. Warm foreground, overlays, and exposure can affect it. Each sharp frame is embedded once and scored against every applicable storm and sunset reference set. Each camera has a `phenomena` map keyed by type: `{"storm": {"score": 0.08, "visible": true}, "sunset": {"score": 0.21, "visible": true}}`. A result is present only when that image filter ran; rejected results have `visible: false`. Storm `score` is the good-minus-rejected OpenCLIP margin, while sunset `score` adds warm-color strength to its OpenCLIP margin. One camera can have both results. Aurora candidates are forecast-based and are not image-filter results in this map.

For a past snapshot, pass a UTC time:

```sh
uv run python storm_map.py --at 2026-09-21T20:00:00Z
```

`--at` selects the most recent ProbSevere file at or before that instant from the [Iowa State MRMS archive](https://mtarchive.geol.iastate.edu/). With no time argument, the script selects the latest published [NOAA NCEP ProbSevere file](https://mrms.ncep.noaa.gov/ProbSevere/PROBSEVERE/). The page uses live OpenStreetMap tiles and the Leaflet library, so it needs an internet connection.

Webcam feed links generally show **current** views even when a saved run is old. The collector archives the exact frames it scores, but an `--at` backfill still uses camera frames and headings available when that backfill runs. It cannot recreate past camera observations. The sunset band follows `--at`; the ICON forecast nearest that time must still be available from DWD's rolling open-data directories.

## Event instances and camera matching

Each ProbSevere feature becomes an event instance with its ID, valid time, original polygon, and a core circle. The circle center is the polygon's area-weighted centroid in a local azimuthal projection; its radius reaches the farthest exterior vertex plus 5 km. A separate visual search circle extends 40 km beyond the core circle to admit cameras that may show peripheral cloud structure. This buffer is an experimental heuristic, not a measured cloud boundary. The original polygon remains available for more precise spatial work.

A camera is a possible view when it is no farther than 100 km from the visual search circle and its heading could intersect that circle. Cameras inside the visual search circle qualify from any heading. Outside it, the circle's angular width relaxes the bearing check as the camera approaches; farther cameras must point more directly toward it. FAA WeatherCams use each view's published bearing and map wedge angle. ALERTWest uses its current pan angle and Iowa Mesonet uses its published angle; both use a provisional 20° pointing tolerance because their feeds do not provide a field-of-view width. USGS HIVIS has no heading in the current camera catalog, so its markers stay dim. These are geometric candidates; the image filter below evaluates their latest available frames.

## Camera image filter

The map first measures each candidate frame's sharpness as the variance of a Laplacian filter on a 320 × 240 grayscale center crop, excluding the outer 10% to reduce timestamp and watermark effects. Frames below 30 are marked with an X and skipped by OpenCLIP. This threshold preserves all seventeen saved good sunset examples and all eight good storm examples; it rejects several soft or obscured bad examples. Smooth skies can be falsely rejected and image noise can hide blur, so the number is a provisional heuristic rather than a guarantee of focus.

The remaining frames are embedded with OpenCLIP. Every embedding is normalized. For each storm candidate, the score is its **mean cosine similarity to confirmed storm views minus its mean cosine similarity to rejected examples**. The rejected set contains both scenic nonstorm views and poor views. Camera tooltips show those means, their two subgroup means, the score, the cutoff, frame time, and Laplacian sharpness. Popups link to the exact scored image.

The OpenCLIP cutoff maximizes balanced accuracy under leave-one-out evaluation of the curated examples. With the current 21 images, the storm cutoff is 0.0603: 6 of 8 good storm views pass and 10 of 13 rejected-view examples fail. The rejected references include two storm-present frames with poor views. This overlap means the filter can reject real storm views; the score is experimental and is not a calibrated probability. Bright dots have at least one visible phenomenon, X markers have none despite qualifying as storm or sunset candidates, and cameras without a candidate view remain dim. Aurora forecast candidates can also be highlighted, without an image-filter result. Hovering over a scored dot or X shows its frame and filter details; clicking shows the same frame and source links. At FAA sites with a scored or aurora-candidate direction, the map also fetches frame metadata for other directions so each choice has a thumbnail. A storm's displayed camera-view count includes geometrically matched cameras with any visible phenomenon. The camera image score is shared by all events whose visual search circles match that camera; these counts do not prove which event appears in the frame.

Top cameras sums a contribution for each accepted storm or sunset view and each forecast-based aurora candidate. Each contribution weights camera-view strength 48% and the strongest matched event score 32%. Laplacian sharpness adds 20% once per camera, using its percentile among frames above the blur threshold on that map; frames below the threshold receive zero. Aurora-only candidates have their frames measured for sharpness without running OpenCLIP. Storm and sunset view strengths are percentiles among accepted image-filter scores in that map; the aurora view strength is 100 minus the camera's forecast cloud-cover percentage. Storm events use ProbSevere interestingness, sunset uses the local ICON sunset estimate, and aurora uses OVATION interestingness after cloud cover. The total can exceed 100 when a camera qualifies for several phenomena. This is an experimental ranking: image noise can raise Laplacian variance, and a camera's geometric match to a specific storm or aurora does not confirm that event in its frame.

An experimental **interestingness** score ranks events using the mean of ProbSevere's next-hour severe-hazard probability and the outline-complexity score. Both components appear in the event popup. This is a ranking heuristic, not an intensity or warning classification.

## Shape complexity

Storm popups show an **outline complexity** score, and the Top events list uses the combined interestingness score. Storm fill color shows severe-weather probability; outline color and thickness show shape complexity. This score uses each ProbSevere polygon and is separate from severe-weather probability. ProbSevere features are single polygons, so their fragmentation term is zero; the wider radar and cloud masks can contain separate pieces.

For the wider precipitation and cloud fields, run the local scene scorer at a latitude and longitude:

```sh
uv run python scene_shapes.py 43.249199 -115.434059
uv run python scene_shapes.py 43.249199 -115.434059 --radius-km 100 --reflectivity-dbz 20
```

The command fetches live [MRMS low-level reflectivity](https://mrms.ncep.noaa.gov/2D/ReflectivityAtLowestAltitude/) and [GOES ABI Clear Sky Mask](https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc%3AC01503) data. GOES-18 covers the western locations and GOES-19 the eastern locations. `--at` selects snapshots at or before a UTC time when they are still present in the MRMS live directory. The script rejects observations more than 15 minutes older than the requested time.

Each mask is scored in a square window around the point, with a half-width of 100 km by default. Rain-area pixels have MRMS reflectivity of at least 20 dBZ by default; cloudy pixels are the GOES mask's probably cloudy or cloudy categories with good quality. The score is 0–100: the mean of jaggedness (`1 − convex-hull perimeter / boundary perimeter`), nonconvexity (`1 − occupied area / convex-hull area`), and fragmentation (`1 − largest piece area / total occupied area`). The first two measurements are weighted by piece area. Pieces smaller than four pixels are ignored by default. The command also reports the number of pieces and the fraction of the window covered.

The score describes geometry at the chosen window and resolution. MRMS reflectivity is a radar echo, not a direct observation of a visible rain curtain; GOES shows cloud cover from above. A high score is a candidate for webcam inspection, not a verified visual-interest label.

## Webcam sources

The map reads public camera metadata and links to each source's live view. The local collector saves copies of candidate frames it scores so an earlier run can display its assessed image; review provider terms before publishing those saved frames beyond a local prototype.

- [ALERTWest](https://alertwest.live/): wide-area fire lookout cameras across western states, including ALERTCalifornia; panoramic views, pointing direction, and current camera pages. Only cameras with an image from the past hour are included.
- [USGS HIVIS](https://apps.usgs.gov/hivis/): public river and landscape cameras across the US, with current images and historical views. Only visible cameras with an image from the past hour are included.
- [FAA WeatherCams](https://weathercams.faa.gov/): wide-angle aviation weather cameras with several directions per site across the US and Canada. Canadian third-party sites operated by NAV CANADA are included when active and not under maintenance, even though the FAA catalog marks most of them unvalidated; the one-hour image freshness check and per-camera maintenance checks still apply. The camera popup names its operator. Each recent view becomes its own camera record with its published bearing and wedge angle. The script reads the public website's catalog with its required Referer; this endpoint is not a documented developer API and could change.
- [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/current/viewer.phtml): recent weather webcam images with location and view angle.

Traffic camera feeds from Washington DOT, Nebraska DOT, and Maryland CHART are disabled for now. Their parsers remain in `cameras.py` for later use. ALERTWest and FAA WeatherCams offer useful horizons, while USGS cameras provide wider geographic coverage. The [NPS webcam API](https://www.nps.gov/subjects/developer/api-documentation.htm) is another promising source of scenic views but requires an API key and is not included in the script.

## Camera view samples

The [FAA camera view samples](data/camera_view_samples/README.md) contain timestamped examples of user-confirmed storm views, scenic views without a storm, and manually reviewed poor views. Presence and view quality are labeled separately. The sample images and source metadata now drive the experimental image filter on the map.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run python -m unittest
```
