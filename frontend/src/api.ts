import type { CameraHistorySample, EventHistory, RunMap, RunSummary } from "./types";

async function readJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json() as Promise<T>;
}

export const getRuns = (before?: number, signal?: AbortSignal) =>
  readJson<RunSummary[]>(`/api/runs?limit=100${before === undefined ? "" : `&before=${before}`}`, signal);

export const getLatest = (signal?: AbortSignal) =>
  readJson<RunSummary>("/api/runs/latest", signal);

export const getRun = (runId: number, signal?: AbortSignal) =>
  readJson<RunMap>(`/api/runs/${runId}`, signal);

export const getEventHistory = (eventId: number, signal?: AbortSignal) =>
  readJson<EventHistory>(`/api/events/${eventId}/history`, signal);

export const getCameraHistory = (network: string, providerId: string, signal?: AbortSignal) => {
  const parameters = new URLSearchParams({ network, provider_id: providerId, limit: "100" });
  return readJson<CameraHistorySample[]>(`/api/cameras/history?${parameters}`, signal);
};
