/** SSE client for the F1 assistant. POST + ReadableStream (EventSource can't POST). */
import { SCENE } from "./store";
import { authHeaders, loadSetup } from "./llmkey";
import { apiFetch } from "./api";

export type AssistantEvent =
  | { type: "text"; text: string; evidence?: EvidenceClass[] }
  | { type: "tool"; name: string }
  | { type: "routes"; routes: { kind: string; geometry: GeoJSON.LineString;
      travel_time_s: number; risk_exposure_s: number }[];
      origin?: string; destination?: string }
  | { type: "query"; scene: string; tick: number; queries: MapQuery[];
      evidence?: EvidenceClass[] }
  | { type: "choices"; pending: PendingChoice[] }
  | { type: "done" }
  | { type: "error"; detail: string };

/** Provenance of a value, from the closed enum in packages/contracts/openapi.yaml. */
export type EvidenceClass = "observed" | "inferred" | "simulated";

/** Engine values a tool surfaced, copied from what the engine already computed. Always
 *  accompanied by the entry's evidence_class — the backend refuses to record one without
 *  the other, so a number can never reach this screen unlabelled. */
export type MapQueryResult = {
  band?: string; depth_p50_cm?: number; pi_passable?: number;
  outcome?: string; travel_min?: number | null; risk_exposure_s?: number | null;
  matched?: string; match_score?: number; source?: string;
  rain_mm_h?: number; tide_m?: number; rain_accum_mm?: number;
  found?: boolean; earliest_in_minutes?: number | null;
  window_minutes?: number; step_minutes?: number;
  segments_by_band?: Record<string, number>; n_worst_streets?: number;
  n_legs?: number;
};

/** The formal, gazetteer-validated query the natural-language turn compiled into.
 *  Shown to the user so the reply can be checked against what was actually asked. */
export type MapQuery = {
  op: string; status: string; query?: string; resolved?: string | string[];
  rejected_field?: string; vehicle?: string; depart_tick?: number; tick?: number;
  origin?: { name: string; match_score: number };
  destination?: { name: string; match_score: number };
  stops?: string[];
  n_comparisons?: number;
  found?: boolean;
  evidence_class?: EvidenceClass;
  result?: MapQueryResult;
};

/** Whether to offer the assistant at all.
 *
 *  True when the server holds a key, when the user already supplied one, *or* when the
 *  endpoint accepts user keys — otherwise a deployment with no server key hides the very
 *  panel where a key would be entered, and the feature is unreachable by construction.
 */
/** An unresolved place name the user must settle. `options` is empty when the name was
 *  not found at all — then only the free-text path is offered, never a near-miss name as
 *  a one-tap button. */
export type PendingChoice = {
  query: string;
  field: string | null;
  options: { name: string; kind_vi: string; detail: string }[];
};

export async function checkAssistant(): Promise<boolean> {
  if (loadSetup()) return true;
  try {
    const r = await apiFetch("/v1/assistant/status");
    if (!r.ok) return false;
    const s = await r.json();
    return s.available === true || s.accepts_user_key === true;
  } catch { return false; }
}

export async function* askAssistant(message: string,
  history: { role: "user" | "assistant"; content: string }[],
  tick: number, vehicle: string): AsyncGenerator<AssistantEvent> {
  const r = await apiFetch("/v1/assistant", {
    method: "POST",
    // The key rides in a header, never in the body: bodies end up in validation
    // errors and request logs, and a credential must reach neither.
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message, history, tick, vehicle, scene: SCENE }),
  });
  if (!r.ok || !r.body) {
    yield { type: "error", detail: `HTTP ${r.status}` };
    return;
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const ev = /^event: (.+)$/m.exec(chunk)?.[1];
      const data = /^data: (.+)$/m.exec(chunk)?.[1];
      if (!ev || !data) continue;
      try {
        yield { type: ev, ...(JSON.parse(data) as object) } as AssistantEvent;
      } catch { /* skip malformed frame */ }
    }
  }
}
