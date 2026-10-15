
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS camera_catalogs (
    id INTEGER PRIMARY KEY,
    digest TEXT NOT NULL UNIQUE,
    camera_keys BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    slot_utc TEXT UNIQUE,
    requested_at_utc TEXT,
    generated_at_utc TEXT NOT NULL,
    map_at_utc TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    catalog_id INTEGER NOT NULL REFERENCES camera_catalogs(id),
    camera_count INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    sunset_json TEXT NOT NULL,
    aurora_json TEXT,
    clouds_json TEXT NOT NULL,
    duration_seconds REAL CHECK (duration_seconds >= 0)
);
CREATE INDEX IF NOT EXISTS runs_generated_idx ON runs(generated_at_utc DESC);
CREATE TABLE IF NOT EXISTS run_sources (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    observed_at_utc TEXT,
    forecast_valid_at_utc TEXT,
    PRIMARY KEY (run_id, source)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    first_seen_at_utc TEXT NOT NULL,
    last_seen_at_utc TEXT NOT NULL,
    UNIQUE (kind, source, source_id, first_seen_at_utc)
);
CREATE INDEX IF NOT EXISTS events_identity_idx
    ON events(kind, source, source_id, last_seen_at_utc DESC);
CREATE TABLE IF NOT EXISTS event_samples (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id),
    run_id INTEGER NOT NULL REFERENCES runs(id),
    valid_at_utc TEXT NOT NULL,
    center_lat REAL,
    center_lon REAL,
    core_radius_km REAL,
    view_radius_km REAL,
    interestingness REAL NOT NULL,
    feature_json TEXT NOT NULL,
    UNIQUE (event_id, run_id)
);
CREATE INDEX IF NOT EXISTS event_samples_run_idx
    ON event_samples(run_id, interestingness DESC);
CREATE INDEX IF NOT EXISTS event_samples_event_time_idx
    ON event_samples(event_id, valid_at_utc);
CREATE TABLE IF NOT EXISTS storm_metrics (
    sample_id INTEGER PRIMARY KEY REFERENCES event_samples(id),
    severe_probability REAL NOT NULL,
    hail_probability REAL NOT NULL,
    wind_probability REAL NOT NULL,
    tornado_probability REAL NOT NULL,
    flashes_5min INTEGER NOT NULL,
    reflectivity_dbz REAL NOT NULL,
    outline_complexity REAL NOT NULL,
    jaggedness REAL NOT NULL,
    nonconvexity REAL NOT NULL,
    fragmentation REAL NOT NULL,
    component_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS aurora_metrics (
    sample_id INTEGER PRIMARY KEY REFERENCES event_samples(id),
    aurora_percent REAL NOT NULL,
    cloud_cover_percent REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cloud_patch_metrics (
    sample_id INTEGER PRIMARY KEY REFERENCES event_samples(id),
    horizontal_variation REAL NOT NULL,
    vertical_variation REAL NOT NULL,
    peak_cloud_fraction REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cameras (
    network TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    catalog_json TEXT NOT NULL,
    PRIMARY KEY (network, provider_id)
);
CREATE TABLE IF NOT EXISTS camera_samples (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    network TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    camera_json TEXT NOT NULL,
    captured_at_utc TEXT,
    frame_url TEXT,
    archived_url TEXT,
    UNIQUE (run_id, network, provider_id),
    FOREIGN KEY (network, provider_id) REFERENCES cameras(network, provider_id)
);
CREATE INDEX IF NOT EXISTS camera_samples_history_idx
    ON camera_samples(network, provider_id, run_id DESC);
CREATE TABLE IF NOT EXISTS camera_event_matches (
    camera_sample_id INTEGER NOT NULL REFERENCES camera_samples(id),
    event_sample_id INTEGER NOT NULL REFERENCES event_samples(id),
    PRIMARY KEY (camera_sample_id, event_sample_id)
);
CREATE INDEX IF NOT EXISTS camera_event_matches_event_idx
    ON camera_event_matches(event_sample_id, camera_sample_id);
CREATE TABLE IF NOT EXISTS camera_view_scores (
    id INTEGER PRIMARY KEY,
    camera_sample_id INTEGER NOT NULL REFERENCES camera_samples(id),
    scorer_key TEXT NOT NULL,
    scorer_version TEXT NOT NULL,
    value REAL NOT NULL,
    threshold REAL,
    passed INTEGER CHECK (passed IN (0, 1)),
    UNIQUE (camera_sample_id, scorer_key)
);
CREATE TABLE IF NOT EXISTS camera_view_score_components (
    score_id INTEGER NOT NULL REFERENCES camera_view_scores(id),
    component_key TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (score_id, component_key)
);
CREATE TABLE IF NOT EXISTS run_artifacts (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY (run_id, kind)
);
