import type { EventKind } from "../core/sky";

// One shape per phenomenon: storm triangle, aurora wave, cloud lines.
const COLOR: Record<EventKind, string> = { storm: "#1F57E0", aurora: "#7A45DC", cloud: "currentColor" };
const ON_DARK: Record<EventKind, string> = { storm: "#7FA2FF", aurora: "#B596FF", cloud: "currentColor" };

function paths(kind: EventKind, color: string): string {
  if (kind === "storm") return `<path d="M7 1.5L13 12H1Z" fill="${color}"/>`;
  if (kind === "aurora") return `<path d="M1 8q3 -5 6 0t6 0" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round"/>`;
  return `<path d="M1.5 5h11M3 9h8" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round"/>`;
}

// String form for map markers, which MapLibre takes as plain DOM elements.
export function symbolSvg(kind: EventKind, size: number, onDark = false): string {
  return `<svg width="${size}" height="${size}" viewBox="0 0 14 14" aria-hidden="true">${paths(kind, (onDark ? ON_DARK : COLOR)[kind])}</svg>`;
}

export const CAMERA_SVG =
  '<svg width="12" height="10" viewBox="0 0 12 10" aria-hidden="true"><rect x=".7" y="2.2" width="10.6" height="7.1" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="6" cy="5.7" r="1.8" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M4 2.2l.8-1.3h2.4L8 2.2" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>';

export function KindSymbol({ kind, size = 12, onDark = false }: { kind: EventKind; size?: number; onDark?: boolean }) {
  const color = (onDark ? ON_DARK : COLOR)[kind];
  return (
    <svg className="kind-symbol" width={size} height={size} viewBox="0 0 14 14" aria-hidden="true">
      {kind === "storm" && <path d="M7 1.5L13 12H1Z" fill={color} />}
      {kind === "aurora" && <path d="M1 8q3 -5 6 0t6 0" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" />}
      {kind === "cloud" && <path d="M1.5 5h11M3 9h8" fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" />}
    </svg>
  );
}
