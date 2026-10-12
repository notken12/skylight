import { useEffect, useMemo, useState } from "react";
import { Outlet, useLoaderData, useLocation, useNavigate, useOutletContext, useRevalidator, useSearchParams, type LoaderFunctionArgs } from "react-router";
import { getLatestRunMap } from "../core/api";
import { buildSky, skyAt, type Sky } from "../core/sky";
import { ModeBar } from "../components/mode-bar";
import { SkyMap } from "../components/sky-map";

// The collector saves a new run every few minutes; check for one this often while the tab is visible.
const REFRESH_MS = 5 * 60_000;
// Sunsets end on the sun's schedule, not the collector's: re-check the sky this often.
const CLOCK_MS = 60_000;

// The sky as of the current minute, for the Explore and Watch routes.
export function useSky(): Sky {
  return useOutletContext<Sky>();
}

export async function rootLoader({ request }: LoaderFunctionArgs): Promise<Sky> {
  return buildSky(await getLatestRunMap({ signal: request.signal }));
}

export function selectedEventId(params: URLSearchParams): number | null {
  const id = Number(params.get("event"));
  return Number.isInteger(id) && id > 0 ? id : null;
}

// Events behind a merged map pill, as ?events=12,34.
export function selectedGroup(params: URLSearchParams): number[] {
  return (params.get("events") ?? "").split(",").map(Number).filter((id) => Number.isInteger(id) && id > 0);
}

export function Root() {
  const run = useLoaderData() as Sky;
  const [now, setNow] = useState(() => new Date());
  const sky = useMemo(() => skyAt(run, now), [run, now]);
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const revalidator = useRevalidator();
  const watching = location.pathname.startsWith("/watch");

  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void revalidator.revalidate();
    }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [revalidator]);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className={watching ? "app is-watching" : "app"}>
      {/* The map stays mounted under Watch so returning to Explore keeps the view. */}
      <SkyMap
        sky={sky}
        now={now}
        selectedId={watching ? null : selectedEventId(params)}
        onSelect={(id) => void navigate(`/?event=${id}`)}
        onSelectGroup={(ids) => void navigate(`/?events=${ids.join(",")}`)}
        onOpenCamera={(key) => void navigate(`/watch?${new URLSearchParams({ camera: key })}`)}
      />
      <Outlet context={sky} />
      <ModeBar />
    </div>
  );
}

export function LoadingScreen() {
  return <main className="status-screen"><p className="mono">Loading the sky…</p></main>;
}

export function ErrorScreen() {
  return (
    <main className="status-screen">
      <h1>Can’t load the sky right now</h1>
      <p>The weather or live camera data didn’t load. Please reload to try again.</p>
    </main>
  );
}
