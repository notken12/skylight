# Skylight storm map

A Python prototype that renders a US map of NOAA ProbSevere v3 storm objects and public webcam locations. Polygon fill represents the modeled chance that a storm will produce **any severe hazard in the next 60 minutes**. It is not an observed intensity or an official warning. Dashed circles show event search areas; bright network-colored camera dots mark possible views, while cameras without a directional match are dimmed gray.

## Run

```sh
uv sync
uv run python storm_map.py
uv run python -m http.server 8765 --bind 127.0.0.1 --directory output
```

Open <http://127.0.0.1:8765/storm_map.html> in a browser while the server is running. Open the generated page, not `map_template.html`. The OpenStreetMap tile service requires a valid browser Referer, which a `file://` page cannot provide.

For a past snapshot, pass a UTC time:

```sh
uv run python storm_map.py --at 2026-09-21T20:00:00Z --output output/previous_storms.html
```

`--at` selects the most recent ProbSevere file at or before that instant from the [Iowa State MRMS archive](https://mtarchive.geol.iastate.edu/). With no time argument, the script selects the latest published [NOAA NCEP ProbSevere file](https://mrms.ncep.noaa.gov/ProbSevere/PROBSEVERE/). The page uses live OpenStreetMap tiles and the Leaflet library, so it needs an internet connection.

Webcam links generally show **current** feeds even for a historical storm snapshot; Iowa Mesonet links point to the latest archived image available when the map was generated. Directional matches use current camera metadata, so they do not establish what a camera saw at a historical storm time.

## Event instances and camera matching

Each ProbSevere feature becomes an event instance with its ID, valid time, original polygon, and an enclosing search circle. The circle center is the polygon's area-weighted centroid in a local azimuthal projection; its radius reaches the farthest exterior vertex plus 5 km. The original polygon remains available for more precise spatial work.

A camera is a possible view when it is no farther than 100 km from the event circle and its heading could intersect the circle. FAA WeatherCams use each view's published bearing and map wedge angle. ALERTWest uses its current pan angle and Iowa Mesonet uses its published angle; both use a provisional 20° pointing tolerance because their feeds do not provide a field-of-view width. USGS HIVIS has no heading in the current camera catalog, so its markers stay dim. These are geometric candidates, not verified images of a storm; terrain, visibility, camera motion, and image content still need checking.

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
- [FAA WeatherCams](https://weathercams.faa.gov/): wide-angle aviation weather cameras with several directions per site. Each active view with an image from the past hour becomes its own camera record. The script reads the public website's catalog with its required Referer; this endpoint is not a documented developer API and could change.
- [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/current/viewer.phtml): recent weather webcam images with location and view angle.

Traffic camera feeds from Washington DOT, Nebraska DOT, and Maryland CHART are disabled for now. Their parsers remain in `cameras.py` for later use. ALERTWest and FAA WeatherCams offer useful horizons, while USGS cameras provide wider geographic coverage. The [NPS webcam API](https://www.nps.gov/subjects/developer/api-documentation.htm) is another promising source of scenic views but requires an API key and is not included in the script.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run python -m unittest
```
