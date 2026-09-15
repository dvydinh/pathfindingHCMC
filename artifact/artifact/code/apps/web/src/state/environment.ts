/** Ambient conditions layer: temperature, humidity, PM2.5/PM10, dust, AQI, UV.
 *
 *  Real Open-Meteo data, unlike every other layer in this demo. Two consequences the UI
 *  must honour: it is badged "observed" rather than "simulated", and it is indexed by the
 *  real clock rather than the scenario tick, so it never moves with the storm slider.
 */
import maplibregl from "maplibre-gl";
import { apiFetch } from "./api";

export const ENV_SRC = "env-tiles";
export const ENV_FILL = "env-tiles-fill";

export type EnvMetric =
  | "apparent_temperature" | "temperature_2m" | "relative_humidity_2m"
  | "pm2_5" | "pm10" | "dust" | "us_aqi" | "uv_index" | "precipitation";

export type EnvSnapshot = {
  time_local: string; timezone: string; n_hours: number; hour_index: number;
  cells: Record<string, number | null>[];
  tiles: { bbox: number[]; cell: number }[];
  n_source_cells: number; source_cell_span_km: number;
  current_hour_index: number;
  uniform_across_scene: Record<string, boolean>;
  units: Record<string, string>;
  source: { weather?: string; air_quality?: string; licence?: string };
  fetched_at: string;
  evidence_class: string; is_synthetic: boolean;
};

/** Break points chosen from published health/comfort thresholds, not from the data's own
 *  range: a colour ramp fitted to today's values would make a calm day look alarming. */
const SCALES: Record<EnvMetric, { stops: number[]; colors: string[] }> = {
  // Heat-index bands (NWS "caution" 27, "extreme caution" 32, "danger" 41).
  apparent_temperature: { stops: [27, 32, 39, 41], colors: ["#2C7FB8", "#7FCDBB", "#FED976", "#FD8D3C", "#BD0026"] },
  temperature_2m:       { stops: [26, 30, 34, 37], colors: ["#2C7FB8", "#7FCDBB", "#FED976", "#FD8D3C", "#BD0026"] },
  relative_humidity_2m: { stops: [50, 65, 80, 90], colors: ["#F7F7F7", "#D1E5F0", "#92C5DE", "#4393C3", "#2166AC"] },
  // Hourly rain. Vietnamese urban drainage is typically overwhelmed well before the
  // upper bands, so the steps follow drainage stress rather than meteorological rarity.
  precipitation: { stops: [0.5, 2.5, 7.5, 15], colors: ["#F7F7F7", "#D1E5F0", "#6BAED6", "#2171B5", "#08306B"] },
  // WHO 2021 24-hour guideline: PM2.5 15, PM10 45 µg/m³.
  pm2_5: { stops: [15, 35, 55, 75], colors: ["#1A9850", "#A6D96A", "#FEE08B", "#F46D43", "#A50026"] },
  pm10:  { stops: [45, 75, 100, 150], colors: ["#1A9850", "#A6D96A", "#FEE08B", "#F46D43", "#A50026"] },
  dust:  { stops: [5, 20, 50, 100], colors: ["#1A9850", "#A6D96A", "#FEE08B", "#F46D43", "#A50026"] },
  // US EPA AQI category boundaries.
  us_aqi: { stops: [50, 100, 150, 200], colors: ["#1A9850", "#FEE08B", "#F46D43", "#A50026", "#7A0177"] },
  uv_index: { stops: [3, 6, 8, 11], colors: ["#1A9850", "#FEE08B", "#F46D43", "#A50026", "#7A0177"] },
};

export function colorFor(metric: EnvMetric, value: number | null): string {
  if (value === null || value === undefined) return "#B7C4CC";
  const { stops, colors } = SCALES[metric];
  let i = 0;
  while (i < stops.length && value >= stops[i]) i++;
  return colors[i];
}

export function scaleFor(metric: EnvMetric) {
  return SCALES[metric];
}

export async function fetchEnv(scene: string, hour: number): Promise<EnvSnapshot> {
  const r = await apiFetch(`/v1/environment?hour=${hour}&scene=${scene}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/** Draw the tiles as hard-edged blocks.
 *
 *  Deliberately not a smooth heatmap: the source resolves to a handful of ~8-11 km cells
 *  over a 6 km scene, so a soft gradient would render spatial detail the data does not
 *  contain — the same failure the coverage layer exists to prevent.
 */
export function drawEnv(map: maplibregl.Map, snap: EnvSnapshot, metric: EnvMetric): void {
  const features = snap.tiles.map((t) => {
    const [w, s, e, n] = t.bbox;
    const v = snap.cells[t.cell]?.[metric] ?? null;
    return {
      type: "Feature" as const,
      properties: { color: colorFor(metric, v as number | null), value: v },
      geometry: {
        type: "Polygon" as const,
        coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
      },
    };
  });
  const data = { type: "FeatureCollection" as const, features };
  const src = map.getSource(ENV_SRC) as maplibregl.GeoJSONSource | undefined;
  if (src) { src.setData(data); return; }
  map.addSource(ENV_SRC, { type: "geojson", data });
  // Under the road edges: ambient context must never obscure the risk layer that the
  // safety case actually rests on.
  const firstLine = map.getStyle().layers?.find((l) => l.type === "line")?.id;
  map.addLayer({
    id: ENV_FILL, type: "fill", source: ENV_SRC,
    paint: { "fill-color": ["get", "color"], "fill-opacity": 0.42 },
  }, firstLine);
}

export function removeEnv(map: maplibregl.Map): void {
  if (map.getLayer(ENV_FILL)) map.removeLayer(ENV_FILL);
  if (map.getSource(ENV_SRC)) map.removeSource(ENV_SRC);
}
