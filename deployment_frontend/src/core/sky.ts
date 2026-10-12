// Turns a saved run into what the app shows: events people can look at and the camera views of them.
// Plain TypeScript with no React or DOM, so a native app can reuse it.
import type { Geometry, Position } from "geojson";
import type { CameraSample, MapEvent, RunMap } from "./types";
import { SUNSET_ELEVATION, sunElevation } from "./sun.ts";

export type EventKind = "storm" | "aurora" | "sunset" | "cloud";

export const EVENT_KINDS: EventKind[] = ["storm", "aurora", "sunset", "cloud"];

export type CameraView = {
  key: string;
  name: string;
  network: string;
  providerId: string;
  direction: string | null;
  latitude: number;
  longitude: number;
  sourceUrl: string;
  rank: number;
  kind: EventKind;
  eventIds: number[];
};

export type SkyEvent = {
  id: number;
  kind: EventKind;
  center: [longitude: number, latitude: number];
  score: number;
  footprint: Geometry;
  views: CameraView[];
};

export type Sky = {
  runId: number;
  generatedAt: string;
  events: SkyEvent[];
  views: CameraView[];
};

const KIND: Record<MapEvent["kind"], EventKind> = { storm: "storm", aurora: "aurora", cloud_patch: "cloud" };

// Cloud tiles cover the whole map; only the most varied ones count as events. Their scores are
// percentiles scaled by a cloud-cover factor, so a fixed cutoff could leave none; take the top few.
const NOTABLE_CLOUDS = 10;

// The backend has no sunset events, only a per-camera sunset image score. The app makes one
// sunset event per camera whose frame passed it, at the camera's position. Their ids are this
// offset plus the camera sample id, so they never collide with backend event ids, but unlike
// those they are not stable across runs. Replace with backend sunset events when they exist.
export const SUNSET_EVENT_ID_BASE = 1_000_000_000;

// A sunset event is shown until the sun sets at its camera, and never from a run older than this,
// so an old run can't bring back yesterday's sunsets before today's.
const SUNSET_MAX_AGE_MS = 3 * 60 * 60_000;

function sunsetPassed(sample: CameraSample): boolean {
  return sample.scores.sunset_view?.passed === true;
}

function eventScore(event: MapEvent): number {
  const properties = event.feature.properties;
  return properties.interestingness?.score ?? properties.score ?? 0;
}

export function cameraKey(network: string, providerId: string): string {
  return `${network}:${providerId}`;
}

function positions(geometry: Geometry): Position[] {
  switch (geometry.type) {
    case "Point":
      return [geometry.coordinates];
    case "MultiPoint":
    case "LineString":
      return geometry.coordinates;
    case "Polygon":
    case "MultiLineString":
      return geometry.coordinates.flat();
    case "MultiPolygon":
      return geometry.coordinates.flat(2);
    case "GeometryCollection":
      return geometry.geometries.flatMap(positions);
  }
}

// Bounding-box centre; footprints that cross the antimeridian are shifted west first.
export function geometryCenter(geometry: Geometry): [number, number] {
  const points = positions(geometry);
  let longitudes = points.map((point) => point[0]);
  if (Math.max(...longitudes) - Math.min(...longitudes) > 180) {
    longitudes = longitudes.map((longitude) => (longitude > 0 ? longitude - 360 : longitude));
  }
  const latitudes = points.map((point) => point[1]);
  return [
    (Math.min(...longitudes) + Math.max(...longitudes)) / 2,
    (Math.min(...latitudes) + Math.max(...latitudes)) / 2,
  ];
}

export function buildSky(run: RunMap): Sky {
  const eventsBySample = new Map(run.events.map((event) => [event.id, event]));

  // A camera counts as a view when its image passed the storm filter for a matched storm,
  // when it is a forecast aurora candidate, or when its image passed the sunset filter.
  const views: CameraView[] = [];
  const sunsetSamples: CameraSample[] = [];
  for (const row of run.cameras) {
    const sample = row.sample;
    if (!sample || sample.camera.link_only) continue;
    const stormPassed = sample.scores.storm_view?.passed === true;
    const seen = sample.event_sample_ids
      .map((id) => eventsBySample.get(id))
      .filter((event): event is MapEvent => event !== undefined)
      .filter((event) => event.kind === "aurora" || (event.kind === "storm" && stormPassed));
    const sunset = sunsetPassed(sample);
    if (sunset) sunsetSamples.push(sample);
    if (seen.length === 0 && !sunset) continue;
    const camera = sample.camera;
    const eventIds = seen.map((event) => event.event_id);
    if (sunset) eventIds.push(SUNSET_EVENT_ID_BASE + sample.id);
    views.push({
      key: cameraKey(camera.network, camera.provider_id),
      name: camera.name,
      network: camera.network,
      providerId: camera.provider_id,
      direction: camera.direction ?? null,
      latitude: camera.latitude,
      longitude: camera.longitude,
      sourceUrl: camera.url,
      rank: sample.scores.overall_rank?.value ?? 0,
      kind: seen.length > 0 ? KIND[seen[0].kind] : "sunset",
      eventIds,
    });
  }
  views.sort((a, b) => b.rank - a.rank);

  const notableClouds = new Set(run.events
    .filter((event) => event.kind === "cloud_patch" && eventScore(event) > 0)
    .sort((a, b) => eventScore(b) - eventScore(a))
    .slice(0, NOTABLE_CLOUDS)
    .map((event) => event.id));

  const events: SkyEvent[] = [];
  for (const event of run.events) {
    if (event.kind === "cloud_patch" && !notableClouds.has(event.id)) continue;
    const circle = event.feature.properties.view_circle;
    events.push({
      id: event.event_id,
      kind: KIND[event.kind],
      center: circle ? [circle.center_longitude, circle.center_latitude] : geometryCenter(event.feature.geometry),
      score: eventScore(event),
      footprint: event.feature.geometry,
      views: views.filter((view) => view.eventIds.includes(event.event_id)),
    });
  }
  for (const sample of sunsetSamples) {
    // Sunsets are made here, not by the backend; see SUNSET_EVENT_ID_BASE.
    const id = SUNSET_EVENT_ID_BASE + sample.id;
    const position: [number, number] = [sample.camera.longitude, sample.camera.latitude];
    events.push({
      id,
      kind: "sunset",
      center: position,
      score: sample.scores.sunset_view.value,
      footprint: { type: "Point", coordinates: position },
      views: views.filter((view) => view.eventIds.includes(id)),
    });
  }
  events.sort((a, b) => b.score - a.score);

  return { runId: run.run.id, generatedAt: run.run.generated_at_utc, events, views };
}

// The sky as it stands at `now`: sunset events whose sun has already set at the camera, or that
// come from a run too old to trust, are dropped along with views that only showed them.
export function skyAt(sky: Sky, now: Date): Sky {
  const runAge = now.getTime() - Date.parse(sky.generatedAt);
  const gone = new Set(sky.events
    .filter((event) => event.kind === "sunset")
    .filter((event) => runAge > SUNSET_MAX_AGE_MS || sunElevation(event.center[1], event.center[0], now) < SUNSET_ELEVATION)
    .map((event) => event.id));
  if (gone.size === 0) return sky;
  const views = sky.views
    .map((view) => ({ ...view, eventIds: view.eventIds.filter((id) => !gone.has(id)) }))
    .filter((view) => view.eventIds.length > 0);
  const events = sky.events
    .filter((event) => !gone.has(event.id))
    .map((event) => ({ ...event, views: views.filter((view) => view.eventIds.includes(event.id)) }));
  return { ...sky, events, views };
}

export function watchable(events: SkyEvent[]): SkyEvent[] {
  return events.filter((event) => event.views.length > 0);
}

// The best watchable event of each kind. Scores use different formulas per kind, so they are
// only compared within a kind.
export function bestOfEachKind(events: SkyEvent[]): SkyEvent[] {
  return EVENT_KINDS.flatMap((kind) => watchable(events).find((event) => event.kind === kind) ?? []);
}
