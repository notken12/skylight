import assert from "node:assert/strict";
import { test } from "node:test";
import { SUNSET_ELEVATION, subsolarPoint, sunElevation, sunsetLine } from "../src/core/sun.ts";
import { SUNSET_EVENT_ID_BASE, buildSky, skyAt } from "../src/core/sky.ts";
import type { CameraSample, RunMap, Score } from "../src/core/types.ts";

// Louisville, Kentucky. Published sunset on 2026-10-03 is about 23:19 UTC (7:19 pm EDT).
const LOUISVILLE = { latitude: 38.25, longitude: -85.76 };

function score(value: number, passed: boolean | null): Score {
  return { value, threshold: null, passed, version: "test", components: {} };
}

function sample(id: number, scores: Record<string, Score>): CameraSample {
  return {
    id,
    camera: { network: "FAA WeatherCams", provider_id: String(id), name: `Camera ${id}`, url: "https://example.com", ...LOUISVILLE },
    captured_at_utc: "2026-10-03T23:00:00Z",
    frame_url: null,
    archived_url: null,
    event_sample_ids: [],
    scores,
  };
}

// One camera whose frame passed the sunset filter and one that did not.
function run(generatedAt: string): RunMap {
  return {
    run: { id: 1, generated_at_utc: generatedAt, map_at_utc: generatedAt },
    events: [],
    cameras: [
      { catalog: sample(7, {}).camera, sample: sample(7, { sunset_view: score(0.3, true), overall_rank: score(40, null) }) },
      { catalog: sample(8, {}).camera, sample: sample(8, { sunset_view: score(0.1, false) }) },
    ],
  };
}

test("the sun is overhead at the equator at the March equinox and at 23.44°N at the June solstice", () => {
  assert.ok(Math.abs(subsolarPoint(new Date("2026-03-20T12:00:00Z"))[1]) < 0.5);
  assert.ok(Math.abs(subsolarPoint(new Date("2026-06-21T12:00:00Z"))[1] - 23.44) < 0.1);
});

test("sun elevation crosses sunset within a few minutes of the published time", () => {
  const { latitude, longitude } = LOUISVILLE;
  assert.ok(sunElevation(latitude, longitude, new Date("2026-10-03T23:10:00Z")) > SUNSET_ELEVATION);
  assert.ok(sunElevation(latitude, longitude, new Date("2026-10-03T23:30:00Z")) < SUNSET_ELEVATION);
});

test("every point on the sunset line is at sunset elevation, in the evening", () => {
  const time = new Date("2026-10-03T23:30:00Z");
  const [sunLongitude] = subsolarPoint(time);
  const points = sunsetLine(time).flat();
  assert.ok(points.length > 100);
  for (const [longitude, latitude] of points) {
    assert.ok(Math.abs(sunElevation(latitude, longitude, time) - SUNSET_ELEVATION) < 0.01);
    const hourAngle = ((((longitude - sunLongitude) % 360) + 540) % 360) - 180;
    assert.ok(hourAngle > 0, `point ${longitude},${latitude} should be east of the sun (evening)`);
  }
});

test("a camera that passed the sunset filter becomes a sunset event with one view", () => {
  const sky = buildSky(run("2026-10-03T23:00:00Z"));
  const sunsets = sky.events.filter((event) => event.kind === "sunset");
  assert.deepEqual(sunsets.map((event) => event.id), [SUNSET_EVENT_ID_BASE + 7]);
  assert.deepEqual(sunsets[0].center, [LOUISVILLE.longitude, LOUISVILLE.latitude]);
  assert.deepEqual(sunsets[0].views.map((view) => view.key), ["FAA WeatherCams:7"]);
  assert.equal(sky.views.length, 1);
  assert.equal(sky.views[0].kind, "sunset");
});

test("sunset events disappear once the sun has set at the camera", () => {
  const sky = buildSky(run("2026-10-03T23:00:00Z"));
  const before = skyAt(sky, new Date("2026-10-03T23:10:00Z"));
  assert.equal(before.events.length, 1);
  assert.equal(before.views.length, 1);
  const after = skyAt(sky, new Date("2026-10-03T23:30:00Z"));
  assert.equal(after.events.length, 0);
  assert.equal(after.views.length, 0);
});

test("sunset events from a run more than three hours old are not shown, even before sunset", () => {
  const sky = buildSky(run("2026-10-02T23:00:00Z"));
  assert.equal(skyAt(sky, new Date("2026-10-03T23:00:00Z")).events.length, 0);
});
