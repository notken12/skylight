# Project memory

## Product vision

Build a web and mobile app that discovers interesting weather phenomena around the world and shows public webcams likely to have a live view of them. Candidate phenomena include thunderstorms, rare clouds, vivid sunrises and sunsets, and aurora. Candidate camera networks include EarthCam, national parks, fire alert networks, resorts, and traffic cameras.

The app should detect and locate an event, find cameras that could see it, and present useful live views to users. Weather severity and the likelihood that a phenomenon is visible from a camera are separate judgments.

## Event instances and interestingness

Represent each detected phenomenon as an event instance with an identity, observation time, source, geographic footprint, and a center latitude/longitude plus radius for nearby-camera searches. Keep the original footprint for more precise camera-facing checks; a circle is only a search approximation. The current storm matcher uses a separate visual search circle 40 km wider than the ProbSevere core circle: cameras inside it qualify from any heading, and more distant cameras qualify when their view intersects it. The added area is a provisional cloud-periphery heuristic, not a measured cloud boundary.

Give each instance an interestingness score for ranking events. The current thunderstorm prototype uses the equal-weight mean of ProbSevere's next-hour severe-hazard probability and outline complexity, preserving both components so users can see why an event ranked highly. This is an experimental ranking heuristic: ProbSevere hazard probabilities are forecasts, not observed storm intensity or official warnings. As other event types are added, their interestingness scores should use the metadata relevant to those phenomena. Score how interesting an event is separately from whether a particular camera has a useful view of it.

## First milestone: thunderstorms

Start with observed thunderstorms rather than broad weather forecasts. For a contiguous-US first release, NOAA ProbSevere v3 provides ready-made, frequently updated storm polygons and next-hour probabilities of severe hail, wind, tornadoes, and any severe hazard. It also includes observed storm attributes such as lightning activity. Join NWS alerts for authoritative warning status. Use GOES lightning observations for additional detection or coverage outside ProbSevere's area, then extend region by region as suitable live data and camera access are verified.

Use official warnings for authoritative severe weather labels. Treat ProbSevere probabilities as next-hour hazard forecasts, not measured intensity or warnings. Treat lightning activity as evidence of an active thunderstorm and a signal for ranking, not as proof that a storm meets severe weather warning criteria. Keep observation time, coverage, provenance, and confidence visible in the data model. Match candidate cameras using location, field of view, freshness, and visibility conditions.

## Interesting storm features

Explore detection of shelf clouds, wall clouds, and other distinctive storm structure. Weather data can prioritize likely storm regions and camera viewpoints; confirmation of these low cloud features requires ground-level imagery or a trustworthy human report. Treat image-based labels as uncertain until validated, especially because shelf clouds, wall clouds, and scud can resemble one another in still frames.

For visually interesting cloud and rain views, assess spatial structure separately from severe-weather risk. Candidate signals are storm footprint and growth, line or arc shape, separated cells, strong reflectivity gradients, rain-area edges, and the angular width and distance of that structure from each camera. ProbSevere polygons and `SIZE` support a first pass, but their storm objects describe convective cores; use gridded MRMS reflectivity or precipitation and GOES imagery to evaluate the wider rain shield and cloud field. Rank individual camera views using bearing, field of view, elevation, and image freshness. Validate proposed visual-interest scores against saved camera frames rather than treating any radar shape as proof of a shelf cloud, wall cloud, or rain curtain.

The first geometry scorer uses area-weighted jaggedness, nonconvexity, and fragmentation to score ProbSevere outlines on the map. The prototype uses outline complexity for exploratory ranking; calibrate it against camera frames before treating that ranking as reliable.

## Camera image filtering

Filter only geometrically matched cameras with a recent snapshot. The first OpenCLIP prototype embeds good storm views and rejected views, then scores a camera by its mean cosine similarity to good storm references minus its mean cosine similarity to rejected references. Rejected references include scenic nonstorm frames and poor views. Poor views may still show a storm: preserve storm presence and view quality as separate labels, and show their component similarities in the UI. Calibrate the cutoff with leave-one-out checks and disclose misses. The current small FAA-heavy sample is a visual-ranking experiment, not verified event-specific detection or a calibrated probability. Preserve each scored frame's capture time and source URL, and keep event interestingness separate from camera view quality.

## Historical runs and app

`analysis_job.py` is a collector. Each successful invocation saves one atomic SQLite run in `output/skylight.sqlite3` with its elapsed duration in `runs.duration_seconds`; a FastAPI server exposes saved runs, event histories, and camera histories to a React Router v7 map. Keep weather source observation and forecast times, run time, and camera frame capture time distinct. `events` holds a persistent identity and constant `kind`; `event_samples` holds the changing footprint and interestingness per run. `camera_samples` holds the candidate camera's frame and viewing metadata; `camera_view_scores` holds sharpness, warm tone, image filters, forecast scores, and rank as versioned rows with optional component rows. Reuse camera catalog identities across runs and keep immutable overlays and scored frames under `output/assets` for historical viewing. A historical `--at` backfill still uses camera views available at collection time; it cannot recover past camera observations.
