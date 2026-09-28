import type { Feature, Geometry } from "geojson";

export type Score = {
  value: number;
  threshold: number | null;
  passed: boolean | null;
  version: string;
  components: Record<string, number>;
};

export type CameraDetails = {
  network: string;
  provider_id: string;
  name: string;
  latitude: number;
  longitude: number;
  url: string;
  direction?: string | null;
  operated_by?: string | null;
  sky_facing?: boolean;
  link_only?: boolean;
};

export type CameraSample = {
  id: number;
  camera: CameraDetails;
  captured_at_utc: string | null;
  frame_url: string | null;
  archived_url: string | null;
  event_sample_ids: number[];
  scores: Record<string, Score>;
};

export type CameraRow = {
  catalog: CameraDetails;
  sample: CameraSample | null;
};

export type EventProperties = {
  id: string;
  region?: string;
  score?: number;
  probability?: number;
  hail_probability?: number;
  wind_probability?: number;
  tornado_probability?: number;
  flashes_5min?: number;
  reflectivity_dbz?: number;
  aurora_percent?: number;
  cloud_cover_percent?: number;
  horizontal_variation?: number;
  vertical_variation?: number;
  peak_cloud_fraction?: number;
  interestingness?: { score: number; severe_probability?: number; outline_complexity?: number };
  outline_shape?: { score: number };
  view_circle?: { center_latitude: number; center_longitude: number; radius_km: number };
};

export type MapEvent = {
  id: number;
  event_id: number;
  kind: "storm" | "aurora" | "cloud_patch";
  source_id: string;
  valid_at_utc: string;
  feature: Feature<Geometry, EventProperties>;
};

export type RunSummary = {
  id: number;
  generated_at_utc: string;
  map_at_utc: string;
  storm_valid_at_utc: string;
  camera_count: number;
  event_count: number;
  duration_seconds: number | null;
};

export type RunMap = {
  run: {
    id: number;
    generated_at_utc: string;
    map_at_utc: string;
    camera_count: number;
    duration_seconds: number | null;
    metadata: Record<string, string>;
    sunset: { band_url: string; quality_url: string; forecast_time: string; source_url: string };
    aurora: { observation_time: string; forecast_time: string; cloud_time: string } | null;
    clouds: { forecast_time: string; source_url: string; tile_degrees: number };
  };
  sources: { source: string; source_url: string; observed_at_utc: string | null; forecast_valid_at_utc: string | null }[];
  events: MapEvent[];
  cameras: CameraRow[];
};

export type EventHistory = {
  event: {
    id: number;
    kind: string;
    source: string;
    source_id: string;
    first_seen_at_utc: string;
    last_seen_at_utc: string;
  };
  samples: {
    id: number;
    run_id: number;
    valid_at_utc: string;
    interestingness: number;
    feature: Feature<Geometry, EventProperties>;
  }[];
};

export type CameraHistorySample = {
  id: number;
  run_id: number;
  captured_at_utc: string | null;
  frame_url: string | null;
  archived_url: string | null;
  generated_at_utc: string;
  scores: { scorer_key: string; value: number; threshold: number | null; passed: number | null }[];
};
