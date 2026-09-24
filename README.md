# Skylight weather map

## Cloud distinctiveness heatmap

The map now shows a toggleable experimental cloud layer over the contiguous US and lists its eight highest-scoring patches. Each 1.5° tile with at least 10% cloud cover and sufficient valid data receives a 0–100 **scene-relative distinctiveness percentile**. Click a tile to inspect cloud coverage, outline complexity, directional alignment, enclosed clear area, median cloud-top height, cloud-top-height variation, median optical depth, and source files. The layer uses live NOAA GOES-18 and GOES-19 [clear-sky masks, cloud-top heights, and cloud optical depths](https://www.ncei.noaa.gov/products/goes-terrestrial-weather-abi-glm).

For each satellite separately, the scorer compares those measurements across scored US tiles in its current scan. It ranks both extreme individual measurements and uncommon combinations of measurements using eight-neighbor distances in feature-rank space. The displayed percentile describes that set of tiles only: even a routine scene has a top-ranked tile. It is **not historical rarity**, a cloud-type classification, or a probability of a good camera view. Nighttime GOES optical depth can saturate at 16, and cloud-top-height variation across a tile is not the physical thickness of a cloud layer. GOES observes clouds from above, so underside features such as mammatus still need ground-level image confirmation. The next calibration step is to compare these feature vectors with archived scenes from similar seasons and local times, then validate high-ranked patches against camera frames.

## Aurora regions

The current map also reads the [NOAA SWPC OVATION 30-minute aurora forecast](https://www.swpc.noaa.gov/products/aurora-30-minute-forecast) and NOAA GFS instantaneous total cloud cover. It groups 1° forecast cells into compact 4° regions when OVATION gives at least 20% aurora probability, GFS cloud cover is at most 30%, and the sun is at least 6° below the horizon at the forecast time. Each region retains its qualifying cells as a footprint and gets an enclosing search circle. The existing direction-aware camera matcher finds candidate views; a camera is highlighted with a purple outline only when its own cloud-cover forecast is at most 30% and it is dark at the camera. Aurora interestingness is the region's peak OVATION probability discounted by its mean forecast cloud cover. These are forecast-based candidate views, not image-confirmed auroras.

The initial cloud request covers 35–80°N and 180–310°E, spanning the current US and Canadian camera catalog. Aurora regions appear only for current maps because the OVATION endpoint serves the latest forecast. Historical `--at` maps show no aurora regions. The map displays the OVATION and GFS valid times and source links. GFS cloud cover is a forecast, not a detected or camera-observed percentage, and a search circle only approximates the visibility area.

## Sunset overlay

The main `storm_map.py` command also draws the sunset band and quality layer. The band covers locations where the sun is between 2° above and 6° below the horizon after solar noon. Inside the continental US portion of that band, a colored 0–100 experimental quality estimate uses live NOAA GFS cloud forecasts. Cameras with a forecast score below 10 are dimmed unless they independently qualify as storm views. Cameras scoring at least 10 are checked with a combined image score: the OpenCLIP good-minus-rejected similarity margin plus the fraction of warm-toned pixels across the entire frame. Accepted views keep their network color with a yellow outline, while rejected views show an X. The lower gate allows a confirmed vivid sunset at McClure Mountain, forecast at 12/100, to reach the image filter. The top sunset camera list ranks accepted views by their combined image score. Hover or click for the frame, forecast score, image score, live feed link, and any storm match details. When several FAA cameras share one location, click the site dot to choose a direction and see that camera's details. Layer controls let you show or hide the band, quality colors, and sunset cameras independently.

The scorer follows the **two phases described in the [SunsetHue whitepaper](https://sunsethue.com/whitepaper)**: trace sunlight through the 3D cloud field to estimate each cell's reflection potential, then trace multiple sight lines from an observer and average their visible reflection. It uses GFS cloud fraction and geopotential height at 21 pressure levels, interpolated onto 0.5 km altitude layers. Middle and high clouds receive more weight. The color scale follows the gray → yellow → orange/red progression visible on the [SunsetHue reference map](https://sunsethue.com/app/maps). SunsetHue does not publish its exact ray sampling, weights, post-processing formulas, or input model, so these numbers are **not** its quality metric and are not calibrated probabilities. This first version does not apply the whitepaper's humidity and golden-hour duration adjustments.

Cloud data priorities for the next iteration:

1. **NOAA HRRR native-level cloud fraction and cloud ice/water fields** over the US for finer 3D cloud geometry and short-range forecasts. Its native-level inventory includes fraction of cloud cover, height, cloud water, and cloud ice by hybrid level; this is more useful for ray tracing than only low/mid/high summaries. [NOAA HRRR product inventory](https://www.nco.ncep.noaa.gov/pmb/products/hrrr/).
2. **GOES-East/West ABI observations** to correct forecast cloud placement and protect high, thin cirrus. The 1.38 µm Band 4 is specifically sensitive to very thin cirrus in daylight; cloud-top height, cloud phase/type, cloud-cover layers, and optical depth add height and translucency information. Near and after sunset Band 4 loses reflected sunlight, so pair it with infrared cloud products rather than treating a dark Band 4 pixel as clear sky. [GOES-R instrument requirements](https://goes-r.noaa.gov/syseng/docs/MRD.pdf), [NOAA cloud products](https://www.star.nesdis.noaa.gov/goesr/product_cp_cloud.php).
3. **Surface humidity, visibility, aerosol/smoke, and more webcam validation** for local visibility and calibration. The forecast score does not use these; webcam frames currently feed only the separate OpenCLIP view filter. The satellite products provide cloud tops and inferred layers, not a complete measured 3D cloud volume; passive satellite views can miss clouds beneath upper layers. [NOAA cloud product research](https://repository.library.noaa.gov/view/noaa/54226/noaa_54226_DS1.pdf).

The GFS layer is a starting forecast, not a live observation. In particular, thin cirrus may still be absent from its modeled cloud fraction. The sunset image filter compares eight user-selected good frames with seven user-selected bad frames and all thirteen rejected storm-view references. Its full-frame combined score cutoff is 0.1491; choosing that cutoff on leave-one-out scores accepts six of eight good frames and rejects nineteen of twenty bad frames. These are exploratory in-sample results, not an independent validation set. The fixed reference images and original URLs are in `data/sunset_view_samples/manifest.json`. A camera's presence in the band alone does not establish its field of view or image quality for sunset. The McClure Mountain frame is a known counterexample to the forecast score: GFS contains high clouds there, but the experimental ray sampling and score scale produced only 12/100. The forecast heatmap still shows that value rather than assigning an unvalidated higher score from a single labeled frame.

A Python prototype that renders a US map of NOAA ProbSevere v3 storm objects, aurora regions, the current sunset band, and public webcam locations. Storm polygon fill represents the modeled chance that a storm will produce **any severe hazard in the next 60 minutes**. It is not an observed intensity or an official warning. Dashed circles show estimated visual search areas; bright network-colored camera dots pass the storm image filter or meet the aurora forecast criteria, X markers are rejected storm or sunset candidates, and cameras without a candidate view are dimmed gray.

## Run

```sh
uv sync
uv run python storm_map.py
uv run python -m http.server 8765 --bind 127.0.0.1 --directory output
```

Open <http://127.0.0.1:8765/storm_map.html> in a browser while the server is running. Open the generated page, not `map_template.html`. The OpenStreetMap tile service requires a valid browser Referer, which a `file://` page cannot provide.

The first run downloads the OpenCLIP `ViT-B-32` `laion2b_s34b_b79k` checkpoint. Generating the map downloads GFS pressure-level and total-cloud-cover fields, samples the forecast quality at each camera, and fetches recent frames for storm candidates and sunset cameras scoring at least 10. Each fetched frame gets a phenomenon-independent warm-tone prevalence score. The score counts pixels with HSV hue ≤55° or ≥335°, saturation ≥0.24, and brightness ≥0.33 across the entire 320 × 240 image. Warm foreground, overlays, and exposure can affect it. Each sharp frame is embedded once and scored against the applicable storm and sunset reference sets. The sunset image score adds warm-tone prevalence directly to the OpenCLIP margin.

For a past snapshot, pass a UTC time:

```sh
uv run python storm_map.py --at 2026-09-21T20:00:00Z --output output/previous_storms.html
```

`--at` selects the most recent ProbSevere file at or before that instant from the [Iowa State MRMS archive](https://mtarchive.geol.iastate.edu/). With no time argument, the script selects the latest published [NOAA NCEP ProbSevere file](https://mrms.ncep.noaa.gov/ProbSevere/PROBSEVERE/). The page uses live OpenStreetMap tiles and the Leaflet library, so it needs an internet connection.

Webcam links generally show **current** feeds even for a historical storm snapshot; Iowa Mesonet links point to the latest archived image available when the map was generated. Directional matches use current camera metadata, so they do not establish what a camera saw at a historical storm or sunset time. The sunset band follows `--at`; the GFS forecast nearest that time must still be available from NOAA's live forecast service.

## Event instances and camera matching

Each ProbSevere feature becomes an event instance with its ID, valid time, original polygon, and a core circle. The circle center is the polygon's area-weighted centroid in a local azimuthal projection; its radius reaches the farthest exterior vertex plus 5 km. A separate visual search circle extends 40 km beyond the core circle to admit cameras that may show peripheral cloud structure. This buffer is an experimental heuristic, not a measured cloud boundary. The original polygon remains available for more precise spatial work.

A camera is a possible view when it is no farther than 100 km from the visual search circle and its heading could intersect that circle. Cameras inside the visual search circle qualify from any heading. Outside it, the circle's angular width relaxes the bearing check as the camera approaches; farther cameras must point more directly toward it. FAA WeatherCams use each view's published bearing and map wedge angle. ALERTWest uses its current pan angle and Iowa Mesonet uses its published angle; both use a provisional 20° pointing tolerance because their feeds do not provide a field-of-view width. USGS HIVIS has no heading in the current camera catalog, so its markers stay dim. These are geometric candidates; the image filter below evaluates their latest available frames.

## Camera image filter

The map first measures each candidate frame's sharpness as the variance of a Laplacian filter on a 320 × 240 grayscale center crop, excluding the outer 10% to reduce timestamp and watermark effects. Frames below 30 are marked with an X and skipped by OpenCLIP. This threshold preserves all eight saved good sunset examples and all eight good storm examples; it rejects several soft or obscured bad examples. Smooth skies can be falsely rejected and image noise can hide blur, so the number is a provisional heuristic rather than a guarantee of focus.

The remaining frames are embedded with OpenCLIP. Every embedding is normalized. For each storm candidate, the score is its **mean cosine similarity to confirmed storm views minus its mean cosine similarity to rejected examples**. The rejected set contains both scenic nonstorm views and poor views. Camera tooltips show those means, their two subgroup means, the score, the cutoff, frame time, and Laplacian sharpness. Popups link to the exact scored image.

The OpenCLIP cutoff maximizes balanced accuracy under leave-one-out evaluation of the curated examples. With the current 21 images, the storm cutoff is 0.0603: 6 of 8 good storm views pass and 10 of 13 rejected-view examples fail. The rejected references include two storm-present frames with poor views. This overlap means the filter can reject real storm views; the score is experimental and is not a calibrated probability. Bright dots pass both image gates, X markers fail either gate, and cameras lacking a qualifying storm or sunset view remain dim. Hovering over a scored dot or X shows its frame and filter details; clicking shows the same frame and source links. A camera image score is shared by all events whose visual search circles geometrically match that camera; this first version does not prove which event appears in the frame.

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

The map reads public camera metadata and links to each source's live view or most recent frame. It does not copy or rebroadcast the feeds.

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
