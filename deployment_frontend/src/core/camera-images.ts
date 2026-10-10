import { readJson } from "./api.ts";
import type { CameraView } from "./sky";

export type CameraImage = { imageUrl: string; capturedAt: string; release?: () => void };
type Images = ReadonlyMap<string, CameraImage>;
type LoadImages = (signal: AbortSignal) => Promise<Images>;

export class CameraImageFeed {
  private images: Images | null = null;
  private error: unknown = null;
  private listeners = new Set<() => void>();
  private timer: ReturnType<typeof setInterval> | undefined;
  private request: AbortController | undefined;

  private readonly intervalMs: number;
  private readonly load: LoadImages;

  constructor(intervalMs: number, load: LoadImages) {
    this.intervalMs = intervalMs;
    this.load = load;
  }

  getSnapshot = (): Images | null => {
    if (this.error !== null) throw this.error;
    return this.images;
  };

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    if (this.listeners.size === 1) {
      document.addEventListener("visibilitychange", this.onVisibilityChange);
      this.resume();
    }
    return () => {
      this.listeners.delete(listener);
      if (this.listeners.size > 0) return;
      document.removeEventListener("visibilitychange", this.onVisibilityChange);
      this.stop();
      this.releaseImages(this.images);
      this.images = null;
    };
  };

  private publish() {
    for (const listener of this.listeners) listener();
  }

  private releaseImages(images: Images | null) {
    if (!images) return;
    for (const image of images.values()) image.release?.();
  }

  private refresh = () => {
    if (this.request) return;
    const request = new AbortController();
    this.request = request;
    void this.load(request.signal).then(
      (images) => {
        if (request.signal.aborted) {
          this.releaseImages(images);
          return;
        }
        this.request = undefined;
        this.releaseImages(this.images);
        this.images = images;
        this.error = null;
        this.publish();
      },
      (error: unknown) => {
        if (request.signal.aborted) return;
        this.request = undefined;
        this.error = error;
        this.stop();
        this.publish();
      },
    );
  };

  private stop() {
    clearInterval(this.timer);
    this.timer = undefined;
    this.request?.abort();
    this.request = undefined;
  }

  private resume() {
    if (document.visibilityState !== "visible") return;
    this.refresh();
    this.timer = setInterval(this.refresh, this.intervalMs);
  }

  private onVisibilityChange = () => {
    this.stop();
    this.resume();
  };
}

type AlertWestCamera = {
  site: { id: string };
  image: { url: string | null; time: string | null };
};

async function alertWestImages(signal: AbortSignal): Promise<Images> {
  const cameras = await readJson<AlertWestCamera[]>(
    "https://api.cdn.prod.alertwest.com/api/firecams/v0/cameras", { signal },
  );
  const images = new Map<string, CameraImage>();
  for (const camera of cameras) {
    if (!camera.image.url || !camera.image.time) continue;
    images.set(camera.site.id, { imageUrl: camera.image.url, capturedAt: camera.image.time });
  }
  return images;
}

type UsgsCamera = {
  camId: string;
  smallDir: string;
  newestImageDT: string | null;
  hideCam: boolean;
};

function versionedImage(url: string, capturedAt: string): string {
  const image = new URL(url);
  image.searchParams.set("at", capturedAt);
  return image.href;
}

async function usgsImages(signal: AbortSignal): Promise<Images> {
  const cameras = await readJson<UsgsCamera[]>(
    "https://api.waterdata.usgs.gov/nims/v0/cameras", { signal },
  );
  const images = new Map<string, CameraImage>();
  for (const camera of cameras) {
    if (camera.hideCam || !camera.newestImageDT) continue;
    images.set(camera.camId, {
      imageUrl: versionedImage(`${camera.smallDir}${camera.camId}_newest.jpg`, camera.newestImageDT),
      capturedAt: camera.newestImageDT,
    });
  }
  return images;
}

type IowaCameras = {
  features: { properties: { cid: string; url: string; valid: string } }[];
};

async function iowaImages(signal: AbortSignal): Promise<Images> {
  const cameras = await readJson<IowaCameras>(
    "https://mesonet.agron.iastate.edu/geojson/webcam.geojson", { signal },
  );
  return new Map(cameras.features.map(({ properties }) => [
    properties.cid, { imageUrl: properties.url, capturedAt: properties.valid },
  ]));
}

async function latestImageHeaders(
  url: string, timeHeader: string, providerId: string, signal: AbortSignal,
): Promise<Images> {
  const response = await fetch(url, { method: "HEAD", signal, cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  const time = response.headers.get(timeHeader);
  if (!time) throw new Error(`Camera response is missing ${timeHeader}: ${url}`);
  const capturedAt = new Date(time).toISOString();
  return new Map([[providerId, { imageUrl: versionedImage(url, capturedAt), capturedAt }]]);
}

async function trexImage(providerId: string, signal: AbortSignal): Promise<Images> {
  const url = `https://api.phys.ucalgary.ca/api/v1/rt/${encodeURIComponent(providerId)}/latest`;
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  const time = response.headers.get("x-rt-stream-last-updated-utc");
  if (!time) throw new Error(`Camera response is missing capture time: ${url}`);
  const imageUrl = URL.createObjectURL(await response.blob());
  return new Map([[providerId, {
    imageUrl, capturedAt: new Date(time).toISOString(), release: () => URL.revokeObjectURL(imageUrl),
  }]]);
}

const sharedFeeds = new Map([
  ["ALERTWest", new CameraImageFeed(5_000, alertWestImages)],
  ["USGS HIVIS", new CameraImageFeed(15_000, usgsImages)],
  ["Iowa Mesonet", new CameraImageFeed(15_000, iowaImages)],
]);
const individualFeeds = new Map<string, CameraImageFeed>();

export function cameraImageFeed(view: CameraView): CameraImageFeed {
  const shared = sharedFeeds.get(view.network);
  if (shared) return shared;
  const existing = individualFeeds.get(view.key);
  if (existing) return existing;
  const feed = individualFeed(view);
  individualFeeds.set(view.key, feed);
  return feed;
}

function individualFeed(view: CameraView): CameraImageFeed {
  const id = encodeURIComponent(view.providerId);
  switch (view.network) {
    case "FAA WeatherCams":
      return new CameraImageFeed(30_000, async (signal) => {
        const image = await readJson<{ image_url: string; captured_at_utc: string }>(
          `/api/cameras/${encodeURIComponent(view.network)}/${id}/latest_image`, { signal },
        );
        return new Map([[view.providerId, {
          imageUrl: image.image_url, capturedAt: image.captured_at_utc,
        }]]);
      });
    case "UCalgary TREx RGB":
      return new CameraImageFeed(1_000, (signal) => trexImage(view.providerId, signal));
    case "AuroraMAX":
      return new CameraImageFeed(2_000, (signal) => latestImageHeaders(
        "https://auroramax.phys.ucalgary.ca/recent/recent_480p.jpg",
        "last-modified", view.providerId, signal,
      ));
    default:
      throw new Error(`No live image source for ${view.network}`);
  }
}
