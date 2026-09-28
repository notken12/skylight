import { useEffect, useRef } from "react";
import L from "leaflet";
import type { Feature, Geometry } from "geojson";
import type { CameraDetails, CameraRow, EventProperties, MapEvent, RunMap, Score } from "./types";

const cameraColors: Record<string, string> = {
  "ALERTWest": "#0891b2",
  "FAA WeatherCams": "#2563eb",
  "USGS HIVIS": "#ec4899",
  "Iowa Mesonet": "#64748b",
  "UCalgary TREx RGB": "#a855f7",
  "AuroraMAX": "#c084fc",
  "Explore.org": "#a78bfa",
  "UAF Allsky": "#8b5cf6",
  "Athabasca AuroraCam": "#d8b4fe",
};

const riskColors = ["#39a96b", "#d5c83d", "#ee9b3b", "#df584e", "#8f3fb0"];
const outlineColors = ["#64748b", "#0891b2", "#4f46e5", "#a21caf", "#e11d48"];
const cloudColors = ["#155e75", "#0d9488", "#6366f1", "#d946ef", "#f43f5e"];

function level(value: number, thresholds: number[], colors: string[]): string {
  for (let index = thresholds.length - 1; index >= 0; index -= 1) {
    if (value >= thresholds[index]) return colors[index];
  }
  throw new Error(`Invalid map score: ${value}`);
}

function requiredNumber(value: number | undefined, label: string): number {
  if (value === undefined) throw new Error(`Missing ${label}`);
  return value;
}

function detail(label: string, value: string | number): HTMLParagraphElement {
  const paragraph = document.createElement("p");
  const strong = document.createElement("strong");
  strong.textContent = `${label}: `;
  paragraph.append(strong, document.createTextNode(String(value)));
  return paragraph;
}

function externalLink(href: string, label: string): HTMLAnchorElement {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.textContent = label;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  return anchor;
}

function eventPopup(event: MapEvent, viewCount: number): HTMLElement {
  const properties = event.feature.properties;
  const content = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = `${event.kind.replace("_", " ")} ${event.source_id}`;
  content.append(title);
  const score = properties.interestingness?.score ?? properties.score;
  if (score !== undefined) content.append(detail("Interestingness", `${score}/100`));
  content.append(detail("Valid", new Date(event.valid_at_utc).toLocaleString()));
  if (event.kind === "storm") {
    content.append(detail("Severe risk, next hour", `${requiredNumber(properties.probability, "severe probability")}%`));
    content.append(detail("Outline complexity", `${requiredNumber(properties.outline_shape?.score, "outline complexity")}/100`));
    content.append(detail("Hail / wind / tornado", `${requiredNumber(properties.hail_probability, "hail probability")}% / ${requiredNumber(properties.wind_probability, "wind probability")}% / ${requiredNumber(properties.tornado_probability, "tornado probability")}%`));
    content.append(detail("Lightning, past 5 min", requiredNumber(properties.flashes_5min, "lightning count")));
    content.append(detail("Peak radar reflectivity", `${requiredNumber(properties.reflectivity_dbz, "reflectivity")} dBZ`));
    content.append(detail("Matched camera views", viewCount));
  }
  if (event.kind === "aurora") {
    content.append(detail("Aurora probability", `${properties.aurora_percent}%`));
    content.append(detail("Cloud cover forecast", `${properties.cloud_cover_percent}%`));
    content.append(detail("Camera candidates", viewCount));
  }
  if (event.kind === "cloud_patch") {
    if (properties.region) content.append(detail("Region", properties.region));
    content.append(detail("Horizontal variation", properties.horizontal_variation ?? 0));
    content.append(detail("Vertical variation", properties.vertical_variation ?? 0));
    content.append(detail("Peak cloud fraction", `${properties.peak_cloud_fraction}%`));
    if (properties.variation_percentile !== undefined) content.append(detail("Variation percentile", `${properties.variation_percentile}/100`));
    if (properties.cover_factor !== undefined) content.append(detail("Cloud-cover factor", `${Math.round(100 * properties.cover_factor)}%`));
  }
  const history = document.createElement("a");
  history.href = `/events/${event.event_id}`;
  history.textContent = "View event history →";
  content.append(history);
  return content;
}

function cameraKey(camera: CameraDetails): string {
  return `${camera.network}:${camera.provider_id}`;
}

function hasAurora(row: CameraRow, events: Map<number, MapEvent>): boolean {
  return row.sample?.event_sample_ids.some((id) => events.get(id)?.kind === "aurora") ?? false;
}

function accepted(row: CameraRow): boolean {
  const scores = row.sample?.scores;
  return scores?.storm_view?.passed === true || scores?.sunset_view?.passed === true;
}

function scoreLine(key: string, score: Score): HTMLElement[] {
  const lines: HTMLElement[] = [detail(key.replaceAll("_", " "), score.value.toFixed(4))];
  if (score.threshold !== null) lines.push(detail("Cutoff", score.threshold.toFixed(4)));
  if (score.passed !== null) lines.push(detail("Result", score.passed ? "accepted" : "rejected"));
  for (const [component, value] of Object.entries(score.components)) {
    lines.push(detail(component.replaceAll("_", " "), value.toFixed(4)));
  }
  return lines;
}

function cameraContent(row: CameraRow, events: Map<number, MapEvent>, links: boolean): HTMLElement {
  const camera = row.sample?.camera ?? row.catalog;
  const content = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = camera.name;
  content.append(title, detail("Network", camera.network));
  if (camera.operated_by) content.append(detail("Operated by", camera.operated_by));
  if (camera.direction) content.append(detail("Facing", camera.direction));
  if (row.sample?.captured_at_utc) content.append(detail("Captured", new Date(row.sample.captured_at_utc).toLocaleString()));
  const imageUrl = row.sample?.archived_url ?? row.sample?.frame_url;
  if (imageUrl) {
    const image = document.createElement("img");
    image.src = imageUrl;
    image.alt = `Saved view from ${camera.name}`;
    image.className = "camera-frame";
    image.decoding = "async";
    content.append(image);
  }
  if (row.sample) {
    const matches = row.sample.event_sample_ids.map((id) => events.get(id));
    if (matches.length > 0) content.append(detail("Candidate for", matches.map((event) => `${event?.kind} ${event?.source_id}`).join(", ")));
    const scoreDetails = document.createElement("details");
    scoreDetails.open = !links;
    const scoreSummary = document.createElement("summary");
    scoreSummary.textContent = "Scoring details";
    scoreDetails.append(scoreSummary);
    for (const [key, score] of Object.entries(row.sample.scores)) {
      if (key === "sunset_band" || key === "aurora_dark") continue;
      if (key === "aurora_cloud_cover" && !hasAurora(row, events)) continue;
      if (key === "overall_rank" || key === "storm_view" || key === "sunset_view") {
        content.append(detail(key.replaceAll("_", " "), `${score.value.toFixed(key === "overall_rank" ? 1 : 4)}${score.passed === null ? "" : score.passed ? " · accepted" : " · rejected"}`));
      }
      scoreDetails.append(...scoreLine(key, score));
    }
    content.append(scoreDetails);
  }
  if (links) {
    if (row.sample?.frame_url) content.append(externalLink(row.sample.frame_url, "Original frame ↗"), document.createElement("br"));
    if (row.sample) {
      const history = document.createElement("a");
      history.href = `/cameras/history?${new URLSearchParams({ network: camera.network, provider_id: camera.provider_id })}`;
      history.textContent = "View camera history →";
      content.append(history, document.createElement("br"));
    }
    content.append(externalLink(camera.url, "Open camera feed ↗"));
  }
  return content;
}

function markerFor(row: CameraRow, events: Map<number, MapEvent>, highlighted: boolean, rejected: boolean): L.Marker | L.CircleMarker {
  const camera = row.sample?.camera ?? row.catalog;
  if (rejected) {
    return L.marker([camera.latitude, camera.longitude], {
      icon: L.divIcon({ className: "rejected-icon", html: "×", iconSize: [16, 16], iconAnchor: [8, 8] }),
    });
  }
  const color = cameraColors[camera.network];
  if (color === undefined) throw new Error(`Unknown camera network: ${camera.network}`);
  const outline = hasAurora(row, events) ? "#c4b5fd" : row.sample?.scores.sunset_view?.passed ? "#f5b541" : "#fff";
  return L.circleMarker([camera.latitude, camera.longitude], {
    radius: highlighted ? 4 : 3,
    color: outline,
    weight: highlighted ? 1 : 0,
    fillColor: color,
    fillOpacity: highlighted ? 1 : 0.25,
  });
}

function displayedCloudFeature(feature: Feature<Geometry, EventProperties>): Feature<Geometry, EventProperties> {
  if (feature.properties.region !== "Western Aleutians") return feature;
  if (feature.geometry.type !== "Polygon") throw new Error("Western Aleutian cloud patch must be a polygon");
  return {
    ...feature,
    geometry: {
      type: "Polygon",
      coordinates: feature.geometry.coordinates.map((ring) =>
        ring.map(([longitude, ...rest]) => [longitude - 360, ...rest]),
      ),
    },
  };
}

export function WeatherMap({ data, selectedCamera }: { data: RunMap; selectedCamera: string | null }) {
  const element = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markers = useRef<Map<string, L.Marker | L.CircleMarker>>(new Map());

  useEffect(() => {
    if (!element.current) throw new Error("Map element is missing");
    const map = L.map(element.current, { preferCanvas: true, zoomControl: false });
    mapRef.current = map;
    markers.current = new Map();
    map.fitBounds([[17, -190], [76, -50]]);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      referrerPolicy: "origin",
    }).addTo(map);

    const sunsetBand = L.imageOverlay(data.run.sunset.band_url, [[-90, -180], [90, 180]], { opacity: 0.7, interactive: false }).addTo(map);
    const sunsetQuality = L.imageOverlay(data.run.sunset.quality_url, [[24.75, -125.25], [50.25, -65.75]], { opacity: 0.9, interactive: false }).addTo(map);
    const eventById = new Map(data.events.map((event) => [event.id, event]));
    const viewCounts = new Map<number, number>();
    for (const row of data.cameras) {
      if (!row.sample) continue;
      for (const id of row.sample.event_sample_ids) {
        if (!eventById.has(id)) throw new Error(`Unknown event match ${id}`);
        if (accepted(row) || hasAurora(row, eventById)) viewCounts.set(id, (viewCounts.get(id) ?? 0) + 1);
      }
    }

    const stormEvents = data.events.filter((event) => event.kind === "storm");
    const auroraEvents = data.events.filter((event) => event.kind === "aurora");
    const cloudEvents = data.events.filter((event) => event.kind === "cloud_patch");
    const stormsBySourceId = new Map(stormEvents.map((event) => [event.source_id, event]));
    const aurorasBySourceId = new Map(auroraEvents.map((event) => [event.source_id, event]));
    const cloudsBySourceId = new Map(cloudEvents.map((event) => [event.source_id, event]));
    const stormLayer = L.geoJSON(stormEvents.map((event) => event.feature), {
      style: (feature) => {
        const properties = feature?.properties;
        if (!properties) throw new Error("Storm properties are missing");
        const outlineScore = requiredNumber(properties.outline_shape?.score, "outline complexity");
        const severeProbability = requiredNumber(properties.probability, "severe probability");
        return {
          color: level(outlineScore, [0, 5, 10, 15, 20], outlineColors),
          weight: 2 + Math.min(4, Math.floor(outlineScore / 5)),
          fillColor: level(severeProbability, [0, 10, 30, 50, 70], riskColors),
          fillOpacity: 0.42,
        };
      },
      onEachFeature: (feature, layer) => {
        const event = stormsBySourceId.get(feature.properties.id);
        if (!event) throw new Error(`Missing storm ${feature.properties.id}`);
        layer.bindPopup(eventPopup(event, viewCounts.get(event.id) ?? 0));
      },
    }).addTo(map);
    const stormCircles = L.layerGroup().addTo(map);
    for (const event of stormEvents) {
      const circle = event.feature.properties.view_circle;
      if (!circle) throw new Error(`Storm ${event.source_id} lacks search circle`);
      L.circle([circle.center_latitude, circle.center_longitude], {
        radius: circle.radius_km * 1000, color: "#eee", weight: 1.5,
        opacity: 0.7, dashArray: "5 5", fillOpacity: 0.015,
      }).bindPopup(eventPopup(event, viewCounts.get(event.id) ?? 0)).addTo(stormCircles);
    }
    const auroraLayer = L.geoJSON(auroraEvents.map((event) => event.feature), {
      style: { color: "#a78bfa", weight: 1, fillColor: "#8b5cf6", fillOpacity: 0.35 },
      onEachFeature: (feature, layer) => {
        const event = aurorasBySourceId.get(feature.properties.id);
        if (!event) throw new Error(`Missing aurora ${feature.properties.id}`);
        layer.bindPopup(eventPopup(event, viewCounts.get(event.id) ?? 0));
      },
    }).addTo(map);
    const cloudLayer = L.geoJSON(cloudEvents.map((event) => displayedCloudFeature(event.feature)), {
      style: (feature) => {
        const score = requiredNumber(feature?.properties?.score, "cloud variation score");
        return { color: "transparent", weight: 0, fillColor: level(score, [0, 35, 70, 90, 98], cloudColors), fillOpacity: score === 0 ? 0 : 0.08 + 0.45 * (score / 100) ** 2 };
      },
      onEachFeature: (feature, layer) => {
        const event = cloudsBySourceId.get(feature.properties.id);
        if (!event) throw new Error(`Missing cloud patch ${feature.properties.id}`);
        layer.bindPopup(eventPopup(event, 0));
      },
    }).addTo(map);

    const cameraLayers = new Map<string, L.LayerGroup>();
    const faaSites = new Map<string, CameraRow[]>();
    for (const row of data.cameras) {
      const camera = row.sample?.camera ?? row.catalog;
      if (camera.network === "FAA WeatherCams") {
        const location = `${camera.latitude},${camera.longitude}`;
        const site = faaSites.get(location) ?? [];
        site.push(row);
        faaSites.set(location, site);
      }
    }
    const addMarker = (rows: CameraRow[]) => {
      const primary = rows.find((row) => accepted(row) || hasAurora(row, eventById)) ?? rows.find((row) => row.sample) ?? rows[0];
      const camera = primary.sample?.camera ?? primary.catalog;
      const highlighted = rows.some((row) => accepted(row) || hasAurora(row, eventById));
      const rejected = !highlighted && rows.some((row) => row.sample);
      const marker = markerFor(primary, eventById, highlighted, rejected);
      marker.bindTooltip(() => cameraContent(primary, eventById, false), { className: "camera-tooltip", direction: "auto", opacity: 0.98 });
      if (rows.length === 1) {
        marker.bindPopup(() => cameraContent(primary, eventById, true));
      } else {
        marker.bindPopup(() => {
          const content = document.createElement("div");
          const choices = document.createElement("div");
          choices.className = "camera-choices";
          const selected = document.createElement("div");
          for (const row of rows) {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = row.sample?.camera.direction ?? row.catalog.direction ?? row.catalog.name;
            button.addEventListener("click", () => selected.replaceChildren(cameraContent(row, eventById, true)));
            choices.append(button);
          }
          selected.append(cameraContent(primary, eventById, true));
          content.append(choices, selected);
          return content;
        });
      }
      const group = cameraLayers.get(camera.network) ?? L.layerGroup().addTo(map);
      cameraLayers.set(camera.network, group);
      marker.addTo(group);
      for (const row of rows) markers.current.set(cameraKey(row.catalog), marker);
    };
    for (const row of data.cameras) {
      const camera = row.sample?.camera ?? row.catalog;
      if (camera.network === "FAA WeatherCams" && faaSites.get(`${camera.latitude},${camera.longitude}`)!.length > 1) continue;
      addMarker([row]);
    }
    for (const site of faaSites.values()) if (site.length > 1) addMarker(site);

    const overlays: Record<string, L.Layer> = {
      "Sunset band": sunsetBand,
      "Sunset quality": sunsetQuality,
      "Storm footprints": stormLayer,
      "Storm search circles": stormCircles,
      "Aurora regions": auroraLayer,
      "3D cloud variation": cloudLayer,
    };
    for (const [network, group] of cameraLayers) overlays[network] = group;
    L.control.layers(undefined, overlays, { collapsed: true }).addTo(map);
    return () => { map.remove(); mapRef.current = null; markers.current.clear(); };
  }, [data]);

  useEffect(() => {
    if (!selectedCamera) return;
    const marker = markers.current.get(selectedCamera);
    if (!marker || !mapRef.current) return;
    mapRef.current.setView(marker.getLatLng(), Math.max(mapRef.current.getZoom(), 8));
    marker.openPopup();
  }, [selectedCamera, data]);

  return <div className="map" ref={element} role="application" aria-label="Weather events and camera views map" />;
}
