import { useEffect } from "react";
import { Outlet, useLoaderData, useLocation, useNavigate, useRevalidator, useSearchParams, type LoaderFunctionArgs } from "react-router";
import { getLatestRunMap } from "../core/api";
import { buildSky, type Sky } from "../core/sky";
import { ModeBar } from "../components/mode-bar";
import { SkyMap } from "../components/sky-map";

// The collector saves a new run every few minutes; check for one this often while the tab is visible.
const REFRESH_MS = 5 * 60_000;

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
  const sky = useLoaderData() as Sky;
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

  return (
    <div className={watching ? "app is-watching" : "app"}>
      {/* The map stays mounted under Watch so returning to Explore keeps the view. */}
      <SkyMap
        sky={sky}
        selectedId={watching ? null : selectedEventId(params)}
        onSelect={(id) => void navigate(`/?event=${id}`)}
        onSelectGroup={(ids) => void navigate(`/?events=${ids.join(",")}`)}
        onOpenCamera={(key) => void navigate(`/watch?${new URLSearchParams({ camera: key })}`)}
      />
      <Outlet />
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
      <p>The weather data didn’t load. Check that the API server is running and has saved at least one run, then reload.</p>
    </main>
  );
}
