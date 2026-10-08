// Mirrors the JSON that backend/weather_queries.read_run_map returns (same shape as frontend/src/types.ts).
// Replace with types generated from the FastAPI OpenAPI schema once the API is versioned.
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
  interestingness?: { score: number };
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
  camera_count: number;
  event_count: number;
};

export type RunMap = {
  run: { id: number; generated_at_utc: string; map_at_utc: string };
  events: MapEvent[];
  cameras: CameraRow[];
};
