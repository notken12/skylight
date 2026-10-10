import { useSyncExternalStore } from "react";
import { cameraImageFeed } from "../core/camera-images";
import { formatAgo } from "../core/format";
import type { CameraView } from "../core/sky";

function useCameraImage(view: CameraView) {
  const feed = cameraImageFeed(view);
  return useSyncExternalStore(feed.subscribe, feed.getSnapshot)?.get(view.providerId);
}

export function CameraImage({ view, className, decorative = false }: {
  view: CameraView;
  className?: string;
  decorative?: boolean;
}) {
  const image = useCameraImage(view);
  if (!image) return <span className={["camera-image-placeholder", className].filter(Boolean).join(" ")} aria-label="Waiting for live camera image" />;
  return <img className={className} src={image.imageUrl} alt={decorative ? "" : `Latest frame from ${view.name}`} />;
}

export function CameraCaptureTime({ view }: { view: CameraView }) {
  const image = useCameraImage(view);
  return <>{image ? `captured ${formatAgo(image.capturedAt)}` : "waiting for live image"}</>;
}
