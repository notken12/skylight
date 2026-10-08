import type { EventKind } from "./sky";

export const KIND_LABEL: Record<EventKind, { one: string; many: string }> = {
  storm: { one: "Storm", many: "Storms" },
  aurora: { one: "Aurora", many: "Aurora zones" },
  cloud: { one: "Cloud pattern", many: "Cloud patterns" },
};

export function formatCoordinates(latitude: number, longitude: number): string {
  const lat = `${Math.abs(latitude).toFixed(2)}°${latitude >= 0 ? "N" : "S"}`;
  const lon = `${Math.abs(longitude).toFixed(2)}°${longitude >= 0 ? "E" : "W"}`;
  return `${lat} ${lon}`;
}

export function formatAgo(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "time unknown";
  const minutes = Math.round((now - Date.parse(iso)) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function formatUtcTime(iso: string): string {
  return `${new Date(iso).toISOString().slice(11, 16)} UTC`;
}

// Many camera names already end in their direction ("Jasper · West"); don't repeat it.
export function facingLabel(name: string, direction: string | null): string {
  if (!direction) return "";
  const word = direction.split(" ")[0].toLowerCase();
  return name.toLowerCase().endsWith(word) ? "" : `facing ${direction}`;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}
