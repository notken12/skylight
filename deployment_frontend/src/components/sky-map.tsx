import { useEffect, useRef } from "react";
import maplibregl, { type GeoJSONSource, type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection, Geometry, Point } from "geojson";
import { EVENT_KINDS, type EventKind, type Sky, type SkyEvent } from "../core/sky";
import { KIND_LABEL, plural } from "../core/format";
import { CAMERA_SVG, symbolSvg } from "./symbols";

// OpenFreeMap: free vector tiles without an API key. Positron is a quiet light base we recolour below.
const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const KIND_COLOR: Record<EventKind, string> = { storm: "#1F57E0", aurora: "#7A45DC", cloud: "#111111" };
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

type Props = {
  sky: Sky;
  selectedId: number | null;
  onSelect: (eventId: number) => void;
  onSelectGroup: (eventIds: number[]) => void;
  onOpenCamera: (cameraKey: string) => void;
};

function collection<P>(features: Feature<Geometry, P>[]): FeatureCollection<Geometry, P> {
  return { type: "FeatureCollection", features };
}

function eventPoints(events: SkyEvent[]) {
  return collection(events.map((event) => ({
    type: "Feature" as const,
    geometry: { type: "Point" as const, coordinates: event.center },
    properties: { id: event.id, kind: event.kind, views: event.views.length },
  })));
}

function isNarrow(): boolean {
  return window.innerWidth < 760;
}

// Keep the focus clear of the side card (desktop) or bottom sheet (phone).
function panelPadding() {
  return isNarrow()
    ? { top: 40, bottom: Math.round(window.innerHeight * 0.5), left: 20, right: 20 }
    : { top: 40, bottom: 120, left: 440, right: 40 };
}

export function SkyMap({ sky, selectedId, onSelect, onSelectGroup, onOpenCamera }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markers = useRef(new Map<string, maplibregl.Marker>());
  const state = useRef({ sky, selectedId, onSelect, onSelectGroup, onOpenCamera, ready: false });
  state.current = { ...state.current, sky, selectedId, onSelect, onSelectGroup, onOpenCamera };

  useEffect(() => {
    if (!container.current) throw new Error("Map container is missing");
    const map = new maplibregl.Map({
      container: container.current,
      style: STYLE_URL,
      center: [-98, 38],
      zoom: isNarrow() ? 1.1 : 1.9,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    // On phones the bottom sheet covers the lower half; centre the globe in the space above it.
    if (isNarrow()) map.setPadding({ top: 0, left: 0, right: 0, bottom: Math.round(window.innerHeight * 0.45) });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

    map.on("style.load", () => {
      map.setProjection({ type: "globe" });
      map.setSky({ "atmosphere-blend": 0 });
      restyleBase(map);
      addLayers(map);
      state.current.ready = true;
      setData(map);
      applySelection(map, false);
    });
    map.on("render", () => syncMarkers(map));
    map.on("click", "cameras", (event) => {
      const key = event.features?.[0]?.properties?.key;
      if (typeof key === "string") state.current.onOpenCamera(key);
    });
    map.on("mouseenter", "cameras", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "cameras", () => { map.getCanvas().style.cursor = ""; });

    return () => {
      map.remove();
      mapRef.current = null;
      markers.current.clear();
    };
    // The map is created once; data and selection changes go through the effects below.
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map && state.current.ready) setData(map);
  }, [sky]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && state.current.ready) applySelection(map, true);
  }, [selectedId]);

  // White land, pale water, thin ink country borders, and no glow around the globe.
  function restyleBase(map: MapLibreMap) {
    for (const layer of map.getStyle().layers) {
      if (layer.type === "background") map.setPaintProperty(layer.id, "background-color", "#FFFFFF");
      if (layer.type === "fill" && layer.id.includes("water")) map.setPaintProperty(layer.id, "fill-color", "#E6EBEF");
    }
    for (const id of ["boundary_2", "boundary_disputed"]) {
      if (!map.getLayer(id)) continue;
      // Ink on the globe, easing to light grey up close where the map gets detailed.
      map.setPaintProperty(id, "line-color", ["interpolate", ["linear"], ["zoom"], 4, "#111111", 7, "#C4C4BF"]);
      map.setPaintProperty(id, "line-opacity", 0.85);
      map.setPaintProperty(id, "line-width", ["interpolate", ["linear"], ["zoom"], 1, 0.5, 5, 0.9, 10, 1.2]);
    }
  }

  function addLayers(map: MapLibreMap) {
    // Draw country borders above rivers and roads, which otherwise break the line into dots.
    // ...but keep them, and the coastline, under the base map's place labels.
    const firstLabel = map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;
    for (const id of ["boundary_disputed", "boundary_2"]) if (map.getLayer(id)) map.moveLayer(id, firstLabel);

    // Ink coastline for the globe and continent views (simplified Natural Earth 1:50m, oceans only).
    // The base map has no coastline layer, and outlining its tiled water would draw tile seams.
    // It fades out by zoom 5.5, where the base map's own shoreline detail takes over.
    map.addSource("coastline", { type: "geojson", data: new URL("/coastline.geojson", window.location.href).href });
    map.addLayer({ id: "coastline", type: "line", source: "coastline", maxzoom: 6, paint: {
      "line-color": "#111111",
      "line-width": ["interpolate", ["linear"], ["zoom"], 1, 0.5, 5, 0.9],
      "line-opacity": ["interpolate", ["linear"], ["zoom"], 3.5, 0.85, 5.5, 0],
    } }, firstLabel);

    map.addSource("footprints", { type: "geojson", data: EMPTY });
    map.addLayer({ id: "footprints-fill", type: "fill", source: "footprints", minzoom: 3.5,
      paint: { "fill-color": KIND_COLOR.storm, "fill-opacity": 0.16 } });
    map.addLayer({ id: "footprints-line", type: "line", source: "footprints", minzoom: 3.5,
      paint: { "line-color": KIND_COLOR.storm, "line-width": 1, "line-opacity": 0.7 } });
    map.addLayer({ id: "footprint-selected", type: "fill", source: "footprints", filter: ["==", ["get", "id"], -1],
      paint: { "fill-color": KIND_COLOR.storm, "fill-opacity": 0.4 } });

    // Events nobody can see stay as small faded dots and are not clickable.
    map.addSource("quiet", { type: "geojson", data: EMPTY });
    map.addLayer({ id: "quiet", type: "circle", source: "quiet", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 2, 6, 4],
      "circle-color": ["match", ["get", "kind"], "storm", KIND_COLOR.storm, "aurora", KIND_COLOR.aurora, KIND_COLOR.cloud],
      "circle-opacity": 0.4,
    } });

    // Watchable events, clustered per kind. The layer is invisible; markers are drawn as HTML pills.
    for (const kind of EVENT_KINDS) {
      map.addSource(`watchable-${kind}`, {
        type: "geojson", data: EMPTY, cluster: true, clusterRadius: 46, clusterMaxZoom: 7,
        clusterProperties: { views: ["+", ["get", "views"]] },
      });
      map.addLayer({ id: `watchable-${kind}`, type: "circle", source: `watchable-${kind}`,
        paint: { "circle-radius": 1, "circle-opacity": 0 } });
    }

    map.addSource("cameras", { type: "geojson", data: EMPTY });
    map.addLayer({ id: "cameras", type: "circle", source: "cameras", paint: {
      "circle-radius": 6, "circle-color": "#111111", "circle-stroke-color": "#FFFFFF", "circle-stroke-width": 2,
    } });
  }

  function setData(map: MapLibreMap) {
    const { events } = state.current.sky;
    const storms = events.filter((event) => event.kind === "storm");
    (map.getSource("footprints") as GeoJSONSource).setData(collection(storms.map((event) => ({
      type: "Feature" as const, geometry: event.footprint, properties: { id: event.id },
    }))));
    (map.getSource("quiet") as GeoJSONSource).setData(eventPoints(events.filter((event) => event.views.length === 0)));
    for (const kind of EVENT_KINDS) {
      const watchable = events.filter((event) => event.kind === kind && event.views.length > 0);
      (map.getSource(`watchable-${kind}`) as GeoJSONSource).setData(eventPoints(watchable));
    }
    for (const marker of markers.current.values()) marker.remove();
    markers.current.clear();
  }

  function syncMarkers(map: MapLibreMap) {
    if (!state.current.ready) return;
    const next = new Map<string, maplibregl.Marker>();
    for (const kind of EVENT_KINDS) {
      for (const feature of map.querySourceFeatures(`watchable-${kind}`)) {
        const properties = feature.properties;
        const cluster = Boolean(properties.cluster);
        const key = cluster ? `${kind}:cluster:${properties.cluster_id}` : `${kind}:${properties.id}`;
        if (next.has(key)) continue;
        const coordinates = (feature.geometry as Point).coordinates as [number, number];
        const marker = markers.current.get(key)
          ?? new maplibregl.Marker({ element: pin(map, kind, properties, cluster, coordinates), opacityWhenCovered: 0 })
            .setLngLat(coordinates)
            .addTo(map);
        next.set(key, marker);
      }
    }
    for (const [key, marker] of markers.current) if (!next.has(key)) marker.remove();
    markers.current = next;
    paintSelectedPin();
  }

  function pin(map: MapLibreMap, kind: EventKind, properties: Record<string, unknown>, cluster: boolean, at: [number, number]) {
    const views = Number(properties.views);
    const count = cluster ? Number(properties.point_count) : 1;
    const label = KIND_LABEL[kind];
    const element = document.createElement("button");
    element.type = "button";
    element.className = cluster ? "pin pin-stack" : "pin";
    element.innerHTML = `${symbolSvg(kind, 12)}${CAMERA_SVG}<span>${views}</span>`;
    element.setAttribute("aria-label", `${cluster ? plural(count, label.one.toLowerCase(), label.many.toLowerCase()) : label.one}, ${plural(views, "camera view")}`);
    if (!cluster) element.dataset.eventId = String(properties.id);
    element.addEventListener("click", (event) => {
      event.stopPropagation();
      if (!cluster) {
        state.current.onSelect(Number(properties.id));
        return;
      }
      // A merged pill zooms in and lists its events in the panel, so one click is enough to pick one.
      const source = map.getSource(`watchable-${kind}`) as GeoJSONSource;
      const clusterId = Number(properties.cluster_id);
      void source.getClusterLeaves(clusterId, count, 0).then((leaves) => {
        state.current.onSelectGroup(leaves.map((leaf) => Number(leaf.properties?.id)));
      });
      void source.getClusterExpansionZoom(clusterId).then((zoom) => {
        map.easeTo({ center: at, zoom: zoom + 0.5, padding: panelPadding() });
      });
    });
    return element;
  }

  function paintSelectedPin() {
    const selected = String(state.current.selectedId);
    for (const marker of markers.current.values()) {
      const element = marker.getElement();
      element.classList.toggle("is-selected", element.dataset.eventId === selected);
    }
  }

  function applySelection(map: MapLibreMap, animate: boolean) {
    const { sky, selectedId } = state.current;
    const event = sky.events.find((candidate) => candidate.id === selectedId);
    map.setFilter("footprint-selected", ["==", ["get", "id"], event?.id ?? -1]);
    (map.getSource("cameras") as GeoJSONSource).setData(collection((event?.views ?? []).map((view) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [view.longitude, view.latitude] },
      properties: { key: view.key },
    }))));
    paintSelectedPin();
    if (!event) return;
    const camera = { center: event.center, zoom: Math.max(map.getZoom(), 6.5), padding: panelPadding() };
    if (animate) map.flyTo({ ...camera, speed: 1.4 });
    else map.jumpTo(camera);
  }

  return <div className="sky-map" ref={container} role="region" aria-label="Map of current weather events" />;
}
