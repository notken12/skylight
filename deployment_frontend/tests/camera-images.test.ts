import assert from "node:assert/strict";
import { setImmediate } from "node:timers/promises";
import { test } from "node:test";
import { CameraImageFeed, cameraImageFeed } from "../src/core/camera-images.ts";
import type { CameraImage } from "../src/core/camera-images.ts";
import type { CameraView } from "../src/core/sky.ts";

const visibility = new EventTarget();
const document = {
  visibilityState: "visible",
  addEventListener: visibility.addEventListener.bind(visibility),
  removeEventListener: visibility.removeEventListener.bind(visibility),
};
Object.defineProperty(globalThis, "document", { value: document, configurable: true });

const frame = { imageUrl: "https://example.com/latest.jpg", capturedAt: "2026-10-10T20:00:00Z" };

function view(network: string, providerId: string): CameraView {
  return {
    key: `${network}:${providerId}`, network, providerId, name: "Camera",
    sourceUrl: "https://example.com", latitude: 40, longitude: -100,
    direction: null, rank: 1, kind: "storm", eventIds: [1],
  };
}

test("subscriptions share polling and stop after the last subscriber leaves", async (context) => {
  context.mock.timers.enable({ apis: ["setInterval"] });
  let calls = 0;
  const feed = new CameraImageFeed(100, async () => {
    calls++;
    return new Map([["1", frame]]);
  });
  const unsubscribeOne = feed.subscribe(() => {});
  const unsubscribeTwo = feed.subscribe(() => {});
  await setImmediate();
  assert.equal(calls, 1);
  assert.equal(feed.getSnapshot()?.get("1"), frame);
  unsubscribeOne();
  context.mock.timers.tick(100);
  await setImmediate();
  assert.equal(calls, 2);
  unsubscribeTwo();
  context.mock.timers.tick(1_000);
  assert.equal(calls, 2);
  assert.equal(feed.getSnapshot(), null);
});

test("hidden tabs abort work and resume immediately without publishing stale requests", async (context) => {
  context.mock.timers.enable({ apis: ["setInterval"] });
  const requests: { signal: AbortSignal; resolve: (images: Map<string, CameraImage>) => void }[] = [];
  const feed = new CameraImageFeed(100, (signal) => new Promise((resolve) => requests.push({ signal, resolve })));
  const unsubscribe = feed.subscribe(() => {});
  context.after(unsubscribe);
  context.after(() => { document.visibilityState = "visible"; });
  context.mock.timers.tick(500);
  assert.equal(requests.length, 1);
  document.visibilityState = "hidden";
  visibility.dispatchEvent(new Event("visibilitychange"));
  assert.equal(requests[0].signal.aborted, true);
  context.mock.timers.tick(500);
  assert.equal(requests.length, 1);
  document.visibilityState = "visible";
  visibility.dispatchEvent(new Event("visibilitychange"));
  assert.equal(requests.length, 2);
  requests[1].resolve(new Map([["1", frame]]));
  await setImmediate();
  requests[0].resolve(new Map([["1", { ...frame, imageUrl: "stale.jpg" }]]));
  await setImmediate();
  assert.equal(feed.getSnapshot()?.get("1")?.imageUrl, frame.imageUrl);
});

test("provider errors propagate to the component rather than displaying archived images", async () => {
  const failure = new Error("Provider unavailable");
  const feed = new CameraImageFeed(100, async () => { throw failure; });
  const unsubscribe = feed.subscribe(() => {});
  await setImmediate();
  unsubscribe();
  assert.throws(feed.getSnapshot, failure);
});

test("ALERTWest cameras share one catalog request and use fresh image timestamps", async (context) => {
  const fetch = context.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify([
    { site: { id: "1" }, image: { url: frame.imageUrl, time: frame.capturedAt } },
    { site: { id: "2" }, image: { url: null, time: null } },
  ])));
  const first = cameraImageFeed(view("ALERTWest", "1"));
  const second = cameraImageFeed(view("ALERTWest", "2"));
  assert.equal(first, second);
  const unsubscribe = first.subscribe(() => {});
  context.after(unsubscribe);
  await setImmediate();
  assert.equal(fetch.mock.callCount(), 1);
  assert.deepEqual(first.getSnapshot()?.get("1"), frame);
  assert.equal(first.getSnapshot()?.has("2"), false);
});

test("FAA uses only the restricted-source endpoint", async (context) => {
  const fetch = context.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({
    image_url: frame.imageUrl, captured_at_utc: frame.capturedAt,
  })));
  const feed = cameraImageFeed(view("FAA WeatherCams", "42"));
  const unsubscribe = feed.subscribe(() => {});
  context.after(unsubscribe);
  await setImmediate();
  assert.equal(fetch.mock.calls[0].arguments[0], "/api/cameras/FAA%20WeatherCams/42/latest_image");
  assert.deepEqual(feed.getSnapshot()?.get("42"), frame);
});

test("Iowa refreshes the archive URL when the catalog publishes a new frame", async (context) => {
  context.mock.timers.enable({ apis: ["setInterval"] });
  let imageUrl = frame.imageUrl;
  context.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ features: [
    { properties: { cid: "KCCI-036", url: imageUrl, valid: frame.capturedAt } },
  ] })));
  const feed = cameraImageFeed(view("Iowa Mesonet", "KCCI-036"));
  const unsubscribe = feed.subscribe(() => {});
  context.after(unsubscribe);
  await setImmediate();
  assert.equal(feed.getSnapshot()?.get("KCCI-036")?.imageUrl, imageUrl);
  imageUrl = "https://example.com/newer-frame.jpg";
  context.mock.timers.tick(15_000);
  await setImmediate();
  assert.equal(feed.getSnapshot()?.get("KCCI-036")?.imageUrl, imageUrl);
});

test("USGS stable latest URLs are versioned with the actual capture timestamp", async (context) => {
  context.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify([
    { camId: "river", smallDir: "https://example.com/720/", newestImageDT: frame.capturedAt, hideCam: false },
  ])));
  const feed = cameraImageFeed(view("USGS HIVIS", "river"));
  const unsubscribe = feed.subscribe(() => {});
  context.after(unsubscribe);
  await setImmediate();
  const image = feed.getSnapshot()?.get("river");
  assert.ok(image);
  const url = new URL(image.imageUrl);
  assert.equal(url.pathname, "/720/river_newest.jpg");
  assert.equal(url.searchParams.get("at"), frame.capturedAt);
  assert.equal(image.capturedAt, frame.capturedAt);
});

test("AuroraMAX polls image headers and versions the direct image URL", async (context) => {
  const fetch = context.mock.method(globalThis, "fetch", async () => new Response(null, {
    headers: { "last-modified": "Sat, 10 Oct 2026 20:00:00 GMT" },
  }));
  const feed = cameraImageFeed(view("AuroraMAX", "https://auroramax.com/live"));
  const unsubscribe = feed.subscribe(() => {});
  context.after(unsubscribe);
  await setImmediate();
  assert.equal(fetch.mock.calls[0].arguments[1]?.method, "HEAD");
  const image = feed.getSnapshot()?.get("https://auroramax.com/live");
  assert.ok(image);
  assert.equal(new URL(image.imageUrl).searchParams.get("at"), "2026-10-10T20:00:00.000Z");
});

test("TREx downloads directly, preserves its capture time and releases image resources", async (context) => {
  const fetch = context.mock.method(globalThis, "fetch", async () => new Response("jpeg", {
    headers: { "x-rt-stream-last-updated-utc": frame.capturedAt },
  }));
  const revoke = context.mock.method(URL, "revokeObjectURL", () => {});
  const feed = cameraImageFeed(view("UCalgary TREx RGB", "trexrgb_fsmi_standard"));
  const unsubscribe = feed.subscribe(() => {});
  await setImmediate();
  assert.equal(fetch.mock.calls[0].arguments[0], "https://api.phys.ucalgary.ca/api/v1/rt/trexrgb_fsmi_standard/latest");
  assert.equal(feed.getSnapshot()?.get("trexrgb_fsmi_standard")?.capturedAt, "2026-10-10T20:00:00.000Z");
  assert.match(feed.getSnapshot()?.get("trexrgb_fsmi_standard")?.imageUrl ?? "", /^blob:/);
  unsubscribe();
  assert.equal(revoke.mock.callCount(), 1);
});
