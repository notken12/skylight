# FAA camera view samples

Twenty-one FAA JPEG snapshots from 2026-09-23, captured around 21:40–22:29 UTC. `manifest.json` records each image's FAA capture time, source page, original image URL, camera ID, label provenance, collection time, and nearby ProbSevere observation time. Open `gallery.html` to review the images.

The labels have two separate purposes:

- `storm_presence`: ten user-confirmed `storm_view` examples, three user-selected `no_storm` scenic views, and eight `unknown` views whose poor quality prevents a reliable weather judgment.
- `view_quality`: eleven `good` views and ten `poor` views. Two of the poor views still show a storm; the others include fog, flat low-contrast sky, a soft horizon, and an obstructing tower.

These are subjective camera-view examples, not independently verified meteorological ground truth. Keep the `unknown` frames out of a binary storm-presence training set. The current OpenCLIP filter uses only `storm_view` + `good` frames as positive references; scenic nonstorm and poor views, including the two poor storm views, are negative references for **view selection**. This small, single-network collection is useful for a similarity prototype and visual review; it is too narrow for a trustworthy global classifier.

`faa_snapshots.py` can collect another batch. Its input is a JSON list of records containing at least `camera_id`; additional fields are copied into the output manifest. For example:

```json
[
  {
    "camera_id": 13402,
    "source_url": "https://weathercams.faa.gov/cameras/cameraSite/927/details/camera/13402/full",
    "label": "unreviewed"
  }
]
```

Run `uv run python faa_snapshots.py input.json --output output/new_snapshots`. Add `--at 2026-09-23T21:50:00Z` to select the latest image before a particular time when it remains in FAA's recent-image feed. That feed is a public website endpoint and may change.
