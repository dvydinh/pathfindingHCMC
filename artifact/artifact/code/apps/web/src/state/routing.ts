import type maplibregl from "maplibre-gl";
import type { RouteBundle } from "../panels/RouteCompare";
import { SCENE } from "./store";
import { apiFetch } from "./api";

export async function requestRoutes(origin: [number, number], dest: [number, number],
  departTick: number, vehicle: string, waypoints: [number, number][] = []): Promise<RouteBundle & {
    routes: (RouteBundle["routes"][number] & { geometry: GeoJSON.LineString })[] }> {
  const r = await apiFetch("/v1/routes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ origin, destination: dest, waypoints,
      depart_tick: departTick, vehicle, scene: SCENE }),
  });
  if (!r.ok) throw new Error(`routes ${r.status}`);
  return r.json();
}

export function drawRoutes(map: maplibregl.Map, bundle: {
  routes: { kind: string; geometry: GeoJSON.LineString }[] }) {
  const byKind: Record<string, string> = {
    fastest_dry: "route-dry", recommended: "route-rec", most_conservative: "route-cons",
  };
  for (const src of Object.values(byKind)) {
    (map.getSource(src) as maplibregl.GeoJSONSource | undefined)
      ?.setData({ type: "FeatureCollection", features: [] });
  }
  for (const r of bundle.routes) {
    const src = byKind[r.kind];
    if (!src) continue;
    (map.getSource(src) as maplibregl.GeoJSONSource | undefined)?.setData({
      type: "Feature", properties: { kind: r.kind }, geometry: r.geometry,
    });
  }
}

export function clearRoutes(map: maplibregl.Map) {
  drawRoutes(map, { routes: [] });
}
