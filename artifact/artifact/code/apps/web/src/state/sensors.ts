/** Sensor coverage layer: which edges the observation network actually informs.
 *
 *  The engine assimilates each observation across up to three graph hops within the same
 *  basin, with a fixed decay, so that footprint — not an optical viewshed — is what
 *  "coverage" means here. Drawing it makes the sparsity legible: in the Thu Duc scenario
 *  38 sensors reach 161 of 25,809 edges, and everything else is inference.
 */
import maplibregl from "maplibre-gl";
import { apiFetch } from "./api";

export const SENSOR_SRC = "sensor-cov";
export const SENSOR_LINE = "sensor-cov-line";
export const SENSOR_PT = "sensor-cov-pt";

export type SensorCoverage = {
  n_sensors: number; n_edges_covered: number; n_edges_total: number;
  pct_edges_covered: number; pct_length_covered: number;
  edge_weight: Record<string, number> | null;
  edge_sensor_count: Record<string, number> | null;
  sensors: { feed_id: string; source_class: string; lon: number; lat: number;
             n_edges_covered: number; covered_m: number; anchor_street: string }[];
  model: { max_hops: number; hop_decay: number[]; constraint: string };
  note: string;
};

export async function fetchCoverage(scene: string): Promise<SensorCoverage> {
  const r = await apiFetch(`/v1/ops/sensor-coverage?scene=${scene}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/** Paint covered edges by assimilation weight, and mark each sensor's anchor. */
export function drawCoverage(map: maplibregl.Map, cov: SensorCoverage): void {
  removeCoverage(map);
  const pts = {
    type: "FeatureCollection" as const,
    features: cov.sensors.map((s) => ({
      type: "Feature" as const,
      properties: { feed_id: s.feed_id, cls: s.source_class },
      geometry: { type: "Point" as const, coordinates: [s.lon, s.lat] },
    })),
  };
  // Weight lives on the existing vector-tile edges via feature-state, so the covered
  // subset lights up in place instead of being redrawn as a second geometry source.
  const w = cov.edge_weight ?? {};
  map.addLayer({
    id: SENSOR_LINE, type: "line", source: "edges",
    filter: ["in", ["get", "edge_id"], ["literal", Object.keys(w)]],
    paint: {
      "line-color": "#7B3FA0", "line-width": 3.2, "line-opacity": 0.9,
      "line-blur": 0.3,
    },
  });
  map.addSource(SENSOR_SRC, { type: "geojson", data: pts });
  map.addLayer({
    id: SENSOR_PT, type: "circle", source: SENSOR_SRC,
    paint: {
      "circle-radius": 5,
      "circle-color": ["match", ["get", "cls"], "camera", "#7B3FA0", "gauge", "#1177AA", "#62727F"],
      "circle-stroke-width": 1.6, "circle-stroke-color": "white",
    },
  });
}

export function removeCoverage(map: maplibregl.Map): void {
  for (const id of [SENSOR_LINE, SENSOR_PT]) if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(SENSOR_SRC)) map.removeSource(SENSOR_SRC);
}
