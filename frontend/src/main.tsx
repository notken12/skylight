import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import {
  createBrowserRouter,
  Link,
  redirect,
  useLoaderData,
  useNavigate,
  useNavigation,
  type LoaderFunctionArgs,
} from "react-router";
import { RouterProvider } from "react-router/dom";
import { getCameraHistory, getEventHistory, getLatest, getRun, getRuns } from "./api";
import { WeatherMap } from "./weather-map";
import type { CameraHistorySample, EventHistory, RunMap, RunSummary } from "./types";
import "leaflet/dist/leaflet.css";
import "./styles.css";

async function latestLoader({ request }: LoaderFunctionArgs) {
  const latest = await getLatest(request.signal);
  return redirect(`/runs/${latest.id}`);
}

async function runLoader({ params, request }: LoaderFunctionArgs) {
  const runId = Number(params.runId);
  if (!Number.isInteger(runId) || runId < 1) throw new Response("Invalid run ID", { status: 400 });
  const [map, runs] = await Promise.all([getRun(runId, request.signal), getRuns(undefined, request.signal)]);
  return { map, runs };
}

async function eventLoader({ params, request }: LoaderFunctionArgs) {
  const eventId = Number(params.eventId);
  if (!Number.isInteger(eventId) || eventId < 1) throw new Response("Invalid event ID", { status: 400 });
  return getEventHistory(eventId, request.signal);
}

async function cameraLoader({ request }: LoaderFunctionArgs) {
  const parameters = new URL(request.url).searchParams;
  const network = parameters.get("network");
  const providerId = parameters.get("provider_id");
  if (!network || !providerId) throw new Response("Camera network and provider ID are required", { status: 400 });
  return { network, providerId, samples: await getCameraHistory(network, providerId, request.signal) };
}

function RunPage() {
  const { map, runs: firstPage } = useLoaderData() as { map: RunMap; runs: RunSummary[] };
  const [runs, setRuns] = useState(firstPage);
  const [selectedCamera, setSelectedCamera] = useState<string | null>(null);
  const navigate = useNavigate();
  const navigation = useNavigation();
  const storms = map.events.filter((event) => event.kind === "storm");
  const rankedCameras = map.cameras
    .filter((camera) => camera.sample?.scores.overall_rank)
    .sort((a, b) => b.sample!.scores.overall_rank.value - a.sample!.scores.overall_rank.value)
    .slice(0, 8);
  const rankedEvents = [...storms]
    .sort((a, b) => (b.feature.properties.interestingness?.score ?? 0) - (a.feature.properties.interestingness?.score ?? 0))
    .slice(0, 8);

  async function loadOlder() {
    if (runs.length === 0) return;
    const older = await getRuns(runs[runs.length - 1].id);
    setRuns((current) => [...current, ...older]);
  }

  return (
    <div className="app-shell">
      <WeatherMap data={map} selectedCamera={selectedCamera} />
      <aside className="panel">
        <header className="panel-header">
          <h1>Weather views</h1>
          <span className="live-indicator" title="Saved observation" />
        </header>
        <label className="run-label" htmlFor="run-select">Saved run</label>
        <select id="run-select" value={map.run.id} onChange={(event) => void navigate(`/runs/${event.target.value}`)}>
          {!runs.some((run) => run.id === map.run.id) && <option value={map.run.id}>Run {map.run.id}</option>}
          {runs.map((run) => (
            <option key={run.id} value={run.id}>{new Date(run.generated_at_utc).toLocaleString()} · #{run.id}</option>
          ))}
        </select>
        <Link className="text-button" to="/">Latest run</Link>
        <button className="text-button" type="button" onClick={() => void loadOlder()}>Load older runs</button>
        <div className="small-meta">
          <div>Storm data {new Date(map.run.metadata.valid_time).toLocaleString()}</div>
          <div>{storms.length} storms · {map.run.camera_count} cameras · {map.cameras.filter((camera) => camera.sample).length} candidates</div>
          {navigation.state !== "idle" && <div>Loading run…</div>}
        </div>
        <details>
          <summary>Top cameras</summary>
          <ol className="rank-list">
            {rankedCameras.map((camera) => (
              <li key={`${camera.catalog.network}:${camera.catalog.provider_id}`}>
                <button type="button" onClick={() => setSelectedCamera(`${camera.catalog.network}:${camera.catalog.provider_id}`)}>
                  <span>{camera.catalog.name}</span>
                  <b>{camera.sample!.scores.overall_rank.value.toFixed(1)}</b>
                </button>
              </li>
            ))}
          </ol>
        </details>
        <details>
          <summary>Top storms</summary>
          <ol className="rank-list">
            {rankedEvents.map((event) => (
              <li key={event.id}>
                <Link to={`/events/${event.event_id}`}>
                  <span>Storm {event.source_id}</span>
                  <b>{event.feature.properties.interestingness?.score.toFixed(1)}</b>
                </Link>
              </li>
            ))}
          </ol>
        </details>
        <details>
          <summary>Map key</summary>
          <div className="legend-item"><i className="legend-line" />Storm search area</div>
          <div className="legend-item"><i className="legend-dot" />Candidate camera with accepted view</div>
          <div className="legend-item"><i className="legend-x">×</i>Rejected candidate</div>
          <p className="fine-print">Storm color shows next-hour severe hazard probability. A bright camera has an accepted image score or a forecast aurora match. Aurora matches are forecast candidates, not confirmed sightings.</p>
          <p className="fine-print">Weather and camera frame times are recorded separately. Saved frames are shown where available.</p>
        </details>
      </aside>
    </div>
  );
}

function EventPage() {
  const history = useLoaderData() as EventHistory;
  const values = history.samples.map((sample) => sample.interestingness);
  const width = 600;
  const height = 120;
  const points = values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * width},${height - (value / 100) * height}`).join(" ");
  return (
    <main className="history-page">
      <Link to={`/runs/${history.samples[history.samples.length - 1].run_id}`}>← Back to map</Link>
      <h1>{history.event.kind} {history.event.source_id}</h1>
      <p>{history.event.source} · {history.samples.length} saved observations</p>
      <div className="history-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Interestingness over time"><polyline points={points} fill="none" stroke="#ddd" strokeWidth="2" />{values.length === 1 && <circle cx={width / 2} cy={height - (values[0] / 100) * height} r="4" fill="#ddd" />}</svg></div>
      <table><thead><tr><th>Valid time</th><th>Interestingness</th><th>Run</th></tr></thead>
        <tbody>{history.samples.map((sample) => <tr key={sample.id}>
          <td>{new Date(sample.valid_at_utc).toLocaleString()}</td>
          <td>{sample.interestingness.toFixed(1)}</td>
          <td><Link to={`/runs/${sample.run_id}`}>View map</Link></td>
        </tr>)}</tbody>
      </table>
    </main>
  );
}

function CameraPage() {
  const { network, providerId, samples } = useLoaderData() as {
    network: string;
    providerId: string;
    samples: CameraHistorySample[];
  };
  return (
    <main className="history-page">
      <Link to={samples.length ? `/runs/${samples[0].run_id}` : "/"}>← Back to map</Link>
      <h1>Camera history</h1>
      <p>{network} · {providerId} · {samples.length} saved candidate views</p>
      <div className="camera-history-grid">
        {samples.map((sample) => (
          <article key={sample.id} className="camera-history-card">
            <Link to={`/runs/${sample.run_id}`}>{new Date(sample.generated_at_utc).toLocaleString()}</Link>
            {(sample.archived_url || sample.frame_url) && <img src={sample.archived_url ?? sample.frame_url ?? undefined} alt={`Camera view captured ${sample.captured_at_utc}`} />}
            <p>Frame {sample.captured_at_utc ? new Date(sample.captured_at_utc).toLocaleString() : "not saved"}</p>
            {sample.scores.map((score) => <p key={score.scorer_key}>{score.scorer_key.replaceAll("_", " ")}: {score.value.toFixed(3)}{score.passed === null ? "" : score.passed ? " · accepted" : " · rejected"}</p>)}
          </article>
        ))}
      </div>
    </main>
  );
}

function ErrorPage() {
  return <main className="error-page"><h1>Unable to load weather data</h1><p>Check that the collector has saved a run and the API server is available.</p></main>;
}

const router = createBrowserRouter([
  { path: "/", loader: latestLoader, ErrorBoundary: ErrorPage },
  { path: "/storm_map.html", loader: latestLoader, ErrorBoundary: ErrorPage },
  { path: "/runs/:runId", loader: runLoader, Component: RunPage, ErrorBoundary: ErrorPage },
  { path: "/events/:eventId", loader: eventLoader, Component: EventPage, ErrorBoundary: ErrorPage },
  { path: "/cameras/history", loader: cameraLoader, Component: CameraPage, ErrorBoundary: ErrorPage },
]);

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><RouterProvider router={router} /></React.StrictMode>,
);
