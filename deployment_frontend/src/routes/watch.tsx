import { useCallback, useEffect, useState } from "react";
import { Link, useRouteLoaderData, useSearchParams } from "react-router";
import type { Sky } from "../core/sky";
import { KIND_LABEL, facingLabel, formatCoordinates } from "../core/format";
import { KindSymbol } from "../components/symbols";
import { CameraCaptureTime, CameraImage } from "../components/camera-image";

const ADVANCE_MS = 12_000;

export function Watch() {
  const sky = useRouteLoaderData("root") as Sky;
  const [params, setParams] = useSearchParams();
  const [paused, setPaused] = useState(false);
  const views = sky.views;
  const index = Math.max(0, views.findIndex((view) => view.key === params.get("camera")));
  const view = views[index];

  const go = useCallback((step: number) => {
    if (views.length === 0) return;
    const next = views[(index + step + views.length) % views.length];
    setParams({ camera: next.key }, { replace: true });
  }, [index, views, setParams]);

  useEffect(() => {
    if (paused || views.length < 2) return;
    const timer = setTimeout(() => go(1), ADVANCE_MS);
    return () => clearTimeout(timer);
  }, [paused, go, views.length]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "ArrowRight") go(1);
      if (event.key === "ArrowLeft") go(-1);
      if (event.key === " ") { event.preventDefault(); setPaused((value) => !value); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  if (!view) {
    return (
      <main className="watch watch-empty">
        <h1>Nothing to watch right now</h1>
        <p>No camera has a clear view of a storm or aurora at the moment. New views appear as the data updates.</p>
      </main>
    );
  }

  const event = sky.events.find((candidate) => view.eventIds.includes(candidate.id));
  const upNext = [1, 2, 3].map((step) => views[(index + step) % views.length]).filter((next) => next.key !== view.key);

  return (
    <main className="watch" aria-label="Camera viewer">
      <CameraImage key={view.key} className="watch-frame" view={view} />
      <div className="scrim scrim-top" />
      <div className="scrim scrim-bottom" />

      <header className="watch-info">
        <span className="eyebrow on-dark"><KindSymbol kind={view.kind} size={11} onDark />{KIND_LABEL[view.kind].one}</span>
        <h1>{view.name}</h1>
        <p className="mono">{[view.network, facingLabel(view.name, view.direction)].filter(Boolean).join(" · ")}</p>
        <p className="mono">{formatCoordinates(view.latitude, view.longitude)} · <CameraCaptureTime view={view} /></p>
      </header>

      <div className="watch-progress">
        <span className="mono">{index + 1} / {views.length}</span>
        <div className="track">
          <i key={view.key} style={{ animationDuration: `${ADVANCE_MS}ms`, animationPlayState: paused ? "paused" : "running" }} />
        </div>
      </div>

      <footer className="watch-controls">
        {event && (
          <Link className="ghost-link" to={`/?event=${event.id}`}>
            See this {KIND_LABEL[event.kind].one.toLowerCase()} on the map
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </Link>
        )}
        <div className="watch-buttons">
          <button type="button" className="round" onClick={() => go(-1)} aria-label="Previous view">
            <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><path d="M12.5 4.5L7 10l5.5 5.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>
          <button type="button" className="round primary" onClick={() => setPaused((value) => !value)} aria-label={paused ? "Play" : "Pause"}>
            {paused
              ? <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><path d="M6 3.5v13l10.5-6.5Z" fill="currentColor" /></svg>
              : <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 4h3v12h-3zM11.5 4h3v12h-3z" fill="currentColor" /></svg>}
          </button>
          <button type="button" className="round" onClick={() => go(1)} aria-label="Next view">
            <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 4.5L13 10l-5.5 5.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>
          <a className="source-link mono" href={view.sourceUrl} target="_blank" rel="noopener noreferrer">Open source feed ↗</a>
        </div>
      </footer>

      {upNext.length > 0 && (
        <aside className="watch-next" aria-label="Up next">
          <span className="eyebrow on-dark">Up next</span>
          <div>
            {upNext.map((next) => (
              <button key={next.key} type="button" onClick={() => setParams({ camera: next.key }, { replace: true })}>
                <CameraImage view={next} decorative />
                <span><KindSymbol kind={next.kind} size={9} onDark />{next.name}</span>
              </button>
            ))}
          </div>
        </aside>
      )}
    </main>
  );
}
