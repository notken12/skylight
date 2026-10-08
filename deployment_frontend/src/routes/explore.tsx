import { Link, useNavigate, useRouteLoaderData, useSearchParams } from "react-router";
import { EVENT_KINDS, bestOfEachKind, watchable, type CameraView, type Sky, type SkyEvent } from "../core/sky";
import { KIND_LABEL, facingLabel, formatAgo, formatCoordinates, formatUtcTime, plural } from "../core/format";
import { KindSymbol } from "../components/symbols";
import { selectedEventId, selectedGroup } from "./root";

export function Explore() {
  const sky = useRouteLoaderData("root") as Sky;
  const [params] = useSearchParams();
  const id = selectedEventId(params);
  const event = sky.events.find((candidate) => candidate.id === id);
  // Keyed so switching events starts fresh: scroll resets and old pictures don't linger.
  if (event) return <EventPanel key={event.id} event={event} />;
  const group = selectedGroup(params);
  const events = sky.events.filter((candidate) => group.includes(candidate.id));
  if (events.length > 0) return <GroupPanel events={events} />;
  return <HomePanel sky={sky} />;
}

function GroupPanel({ events }: { events: SkyEvent[] }) {
  const kinds = new Set(events.map((event) => event.kind));
  const label = kinds.size === 1 ? KIND_LABEL[events[0].kind].many.toLowerCase() : "events";
  return (
    <section className="panel" aria-labelledby="group-title">
      <BackLink />
      <h1 id="group-title" className="title-lg">{events.length} {label} here</h1>
      <EventList events={events} />
    </section>
  );
}

function EventList({ events }: { events: SkyEvent[] }) {
  const navigate = useNavigate();
  return (
    <ul className="event-list">
      {events.map((event) => (
        <li key={event.id}>
          <button type="button" className="event-row" onClick={() => void navigate(`/?event=${event.id}`)}>
            {event.views[0] && <img className="thumb" src={event.views[0].imageUrl} alt="" loading="lazy" />}
            <span className="event-row-text">
              <span className="event-row-title"><KindSymbol kind={event.kind} size={11} />{KIND_LABEL[event.kind].one}</span>
              <span className="mono muted">{formatCoordinates(event.center[1], event.center[0])}</span>
              <span className="mono muted">{plural(event.views.length, "camera")}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function BackLink() {
  return (
    <Link to="/" className="back-link">
      <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3L5 8l5 5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
      All events
    </Link>
  );
}

function HomePanel({ sky }: { sky: Sky }) {
  const visible = watchable(sky.events);
  const best = bestOfEachKind(sky.events);
  return (
    <section className="panel" aria-labelledby="home-title">
      <header className="panel-head">
        <span className="wordmark">skylight</span>
        <span className="mono muted" title={formatUtcTime(sky.generatedAt)}>updated {formatAgo(sky.generatedAt)}</span>
      </header>
      <h1 id="home-title" className="title-xl">The sky right now</h1>
      <ul className="counts">
        {EVENT_KINDS.map((kind) => {
          const count = visible.filter((event) => event.kind === kind).length;
          return (
            <li key={kind}>
              <KindSymbol kind={kind} size={13} />
              <span>{KIND_LABEL[kind].many}</span>
              <span className="mono">{count === 0 ? "none visible" : `${count} visible`}</span>
            </li>
          );
        })}
      </ul>
      <h2 className="eyebrow">Most interesting now</h2>
      {best.length === 0
        ? <p className="muted">No camera has a clear view of a storm or aurora right now. New views appear as the data updates.</p>
        : <EventList events={best} />}
    </section>
  );
}

function EventPanel({ event }: { event: SkyEvent }) {
  const [first, ...rest] = event.views;
  return (
    <section className="panel" aria-labelledby="event-title">
      <BackLink />
      <div className="event-head">
        <h1 id="event-title" className="title-lg"><KindSymbol kind={event.kind} size={16} />{KIND_LABEL[event.kind].one}</h1>
        <p className="mono muted">{formatCoordinates(event.center[1], event.center[0])}</p>
      </div>
      {first ? (
        <>
          <h2 className="section-title">{plural(event.views.length, "camera")} can see it</h2>
          <CameraCard view={first} large />
          {rest.length > 0 && <div className="camera-grid">{rest.map((view) => <CameraCard key={view.key} view={view} />)}</div>}
        </>
      ) : (
        <p className="muted">No camera has a clear view of this right now.</p>
      )}
    </section>
  );
}

function CameraCard({ view, large = false }: { view: CameraView; large?: boolean }) {
  return (
    <Link className={large ? "camera-card large" : "camera-card"} to={`/watch?${new URLSearchParams({ camera: view.key })}`}>
      <img key={view.imageUrl} src={view.imageUrl} alt={`Latest frame from ${view.name}`} loading="lazy" />
      <span className="camera-name">{view.name}</span>
      <span className="mono muted">{[facingLabel(view.name, view.direction), formatAgo(view.capturedAt)].filter(Boolean).join(" · ")}</span>
    </Link>
  );
}
