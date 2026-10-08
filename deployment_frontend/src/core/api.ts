import type { RunMap, RunSummary } from "./types";

// baseUrl is empty on the web (same origin); a native app passes the server's address.
export type ApiOptions = { baseUrl?: string; signal?: AbortSignal };

async function readJson<T>(path: string, { baseUrl = "", signal }: ApiOptions = {}): Promise<T> {
  const response = await fetch(baseUrl + path, { signal });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${path}`);
  return response.json() as Promise<T>;
}

export const getLatestRun = (options?: ApiOptions) => readJson<RunSummary>("/api/runs/latest", options);

export const getRunMap = (runId: number, options?: ApiOptions) => readJson<RunMap>(`/api/runs/${runId}`, options);

export async function getLatestRunMap(options?: ApiOptions): Promise<RunMap> {
  const latest = await getLatestRun(options);
  return getRunMap(latest.id, options);
}
