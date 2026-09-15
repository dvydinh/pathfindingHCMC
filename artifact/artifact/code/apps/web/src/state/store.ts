/** Scene state fetching + client-side cache. Order of arrays matches edges.geojson. */
import { apiFetch } from "./api";
export const SCENE: string =
  new URLSearchParams(location.search).get("scene") ?? "thuduc";

export type SceneState = {
  model_version: string; tick: number; vehicle: string;
  bands: number[]; pi: number[]; p50_cm: number[]; width_cm: number[];
  age_s: number[]; evidence_class: string; is_synthetic: boolean;
};
export const BAND_NAME = ["low", "unknown", "uncertain", "avoid"] as const;

const cache = new Map<string, Promise<SceneState>>();
let cacheVersion = 0;

export function invalidateStateCache() { cache.clear(); cacheVersion++; }

export function fetchState(tick: number, vehicle: string): Promise<SceneState> {
  const key = `${tick}|${vehicle}|${cacheVersion}`;
  if (!cache.has(key)) {
    cache.set(key, apiFetch(`/v1/state?at=${tick}&vehicle=${vehicle}&scene=${SCENE}`).then((r) => {
      if (!r.ok) throw new Error(`state ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(key)!;
}

export type EdgeDetail = {
  edge_id: string; pi: number; risk_band: string; evidence_age_s: number;
  source_mix: Record<string, number>; reason_codes: string[]; is_synthetic: boolean;
  depth_q: { p50: number; width: number };
  fan: { tick: number; p10: number; p50: number; p90: number }[];
};

export async function fetchEdgeDetail(edgeId: string, tick: number, vehicle: string):
  Promise<EdgeDetail> {
  const r = await apiFetch(`/v1/passability?at=${tick}&vehicle=${vehicle}&scene=${SCENE}&edge_id=${encodeURIComponent(edgeId)}`);
  if (!r.ok) throw new Error(`passability ${r.status}`);
  return (await r.json()).edges[0];
}
