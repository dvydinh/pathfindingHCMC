import { useEffect, useRef, useState } from "react";
import type maplibregl from "maplibre-gl";
import { RISK, UI } from "../design/palette";
import { t, type Lang } from "../state/i18n";
import { askAssistant, type MapQuery, type PendingChoice, type EvidenceClass }
  from "../state/assistant";
import { LlmKeySetup } from "./LlmKeySetup";
import { loadSetup, type LlmSetup } from "../state/llmkey";
import { drawRoutes } from "../state/routing";
import { apiFetch } from "../state/api";

type Msg = { role: "user" | "assistant"; content: string; tool?: string;
             queries?: MapQuery[]; choices?: PendingChoice[];
             evidence?: EvidenceClass[] };

/** Colour and wording per provenance class. Deliberately not all one colour: the whole
 *  point is that "from OpenStreetMap" and "from the synthetic storm" are different
 *  claims and a reader should be able to tell them apart without reading the words. */
const EV_STYLE: Record<string, { bg: string; fg: string; key: string }> = {
  observed:  { bg: "#E6F2EC", fg: "#12684F", key: "ev.observed" },
  inferred:  { bg: "#FDF2DC", fg: "#8A5B12", key: "ev.inferred" },
  simulated: { bg: UI.paleBlue, fg: UI.blue,  key: "ev.simulated" },
};

/** Provenance badges under one answer. An answer backed by no engine value gets the
 *  "no engine data" badge instead of nothing — a refusal lands here, and silence would
 *  read as authority the reply has not earned. */
function EvidenceBadges({ evidence, lang }: { evidence?: EvidenceClass[]; lang: Lang }) {
  const list = evidence ?? [];
  const chip = (bg: string, fg: string, label: string, k: string) => (
    <span key={k} style={{
      fontSize: 8, fontWeight: 700, letterSpacing: .2, background: bg, color: fg,
      padding: "1px 5px", borderRadius: 3, whiteSpace: "nowrap",
    }}>{label}</span>
  );
  return (
    <div style={{ display: "flex", gap: 4, marginTop: 4, flexWrap: "wrap" }}>
      {list.length === 0
        ? chip("#F3F0EC", UI.mid, t("ev.none", lang), "none")
        : list.map((e) => {
            const s = EV_STYLE[e] ?? EV_STYLE.simulated;
            return chip(s.bg, s.fg, t(s.key, lang), e);
          })}
    </div>
  );
}

/** Engine values a tool returned, rendered so no number ever appears without the
 *  provenance label that belongs to it. */
function resultLine(q: MapQuery): string {
  const r = q.result;
  if (!r) return "";
  const bits: string[] = [];
  if (r.matched !== undefined) bits.push(`khớp "${r.matched}" (${r.match_score})`);
  if (r.band !== undefined) bits.push(`band=${r.band}`);
  if (r.depth_p50_cm !== undefined) bits.push(`p50=${r.depth_p50_cm}cm`);
  if (r.pi_passable !== undefined) bits.push(`π=${r.pi_passable}`);
  if (r.outcome !== undefined) bits.push(r.outcome);
  if (r.travel_min != null) bits.push(`${r.travel_min} phút`);
  if (r.risk_exposure_s != null) bits.push(`phơi nhiễm ${r.risk_exposure_s}s`);
  if (r.rain_mm_h !== undefined) bits.push(`mưa ${r.rain_mm_h}mm/h`);
  if (r.tide_m !== undefined) bits.push(`triều ${r.tide_m}m`);
  if (r.rain_accum_mm !== undefined) bits.push(`tích luỹ ${r.rain_accum_mm}mm`);
  if (r.found !== undefined) bits.push(r.found ? "có mốc đi được" : "không có mốc đạt chuẩn");
  if (r.earliest_in_minutes != null) bits.push(`sớm nhất +${r.earliest_in_minutes} phút`);
  if (r.window_minutes !== undefined) bits.push(`quét ${r.window_minutes} phút`);
  if (r.n_legs !== undefined) bits.push(`${r.n_legs} chặng`);
  if (r.n_worst_streets !== undefined) bits.push(`${r.n_worst_streets} tuyến xấu nhất`);
  if (r.segments_by_band) {
    bits.push(Object.entries(r.segments_by_band).map(([b, n]) => `${b}:${n}`).join(" "));
  }
  return bits.join(", ");
}

/** One line of the formal query, in the user's terms. Reading this is how a user
 *  checks that the assistant understood the right places before trusting the reply. */
function queryLine(q: MapQuery): string {
  const place = (p?: { name: string }) => p?.name ?? "?";
  if (q.op === "plan_route" && q.status === "executed")
    return `tuyến: ${place(q.origin)} → ${place(q.destination)} · tick ${q.depart_tick} · ${q.vehicle}`;
  if (q.op === "plan_route") return `tuyến bị từ chối (${q.status}): ${q.query ?? ""}`;
  if (q.op === "plan_trip" && q.status === "executed")
    return `chuyến: ${q.stops?.join(" → ")} · tick ${q.depart_tick} · ${q.vehicle}` +
      (q.n_comparisons ? ` · so sánh ${q.n_comparisons} phương án` : "");
  if (q.op === "plan_trip") return `chuyến bị từ chối (${q.status}): ${q.rejected_field ?? ""}`;
  if (q.op === "find_place")
    return `tra "${q.query}" → ${q.status === "ok"
      ? (Array.isArray(q.resolved) ? q.resolved[0] : q.resolved)
      : q.status}`;
  if (q.op === "get_street_state") return `trạng thái tuyến: ${q.resolved} · tick ${q.tick}`;
  if (q.op === "get_area_summary") return `tổng quan khu vực · tick ${q.tick}`;
  if (q.op === "get_area_weather") return `thời tiết khu vực · tick ${q.tick}`;
  if (q.op === "get_edge_state")
    return `trạng thái đoạn ${q.query}${q.resolved ? ` (${q.resolved})` : ""} · tick ${q.tick}`;
  if (q.op === "find_departure_window" && q.status === "executed")
    return `tìm giờ đi được: ${Array.isArray(q.query) ? q.query.join(" → ") : q.query} · ${q.vehicle}`;
  if (q.op === "find_departure_window")
    return `tìm giờ đi được bị từ chối (${q.status}): ${q.rejected_field ?? ""}`;
  return `${q.op} (${q.status})`;
}

export function AssistantPanel({ tick, vehicle, lang, mapRef, onClose }: {
  tick: number; vehicle: string; lang: Lang;
  mapRef: { current: maplibregl.Map | null }; onClose: () => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [activity, setActivity] = useState<string | null>(null);
  const [setup, setSetup] = useState<LlmSetup | null>(loadSetup());
  const [serverKey, setServerKey] = useState(true);   // assume yes until status says no

  useEffect(() => {
    apiFetch("/v1/assistant/status")
      .then((r) => r.json())
      .then((s) => setServerKey(s.available === true))
      .catch(() => setServerKey(false));
  }, []);
  const canSend = serverKey || setup !== null;
  const scroller = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [msgs, activity]);

  const send = async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text || busy || !canSend) return;
    if (!override) setInput("");
    setBusy(true);
    const history = msgs.filter((m) => !m.tool)
      .map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: "user", content: text }]);
    let gotText = false;
    try {
      for await (const ev of askAssistant(text, history, tick, vehicle)) {
        if (ev.type === "tool") {
          setActivity(t(`assistant.tool.${ev.name}`, lang));
        } else if (ev.type === "text") {
          gotText = true;
          setActivity(null);
          setMsgs((m) => [...m, { role: "assistant", content: ev.text,
                                  evidence: ev.evidence }]);
        } else if (ev.type === "choices") {
          setMsgs((m) => [...m, { role: "assistant", tool: "choices",
            content: "", choices: ev.pending }]);
        } else if (ev.type === "query") {
          setMsgs((m) => [...m, { role: "assistant", tool: "query",
            content: t("assistant.query", lang), queries: ev.queries }]);
        } else if (ev.type === "routes" && mapRef.current && ev.routes.length) {
          drawRoutes(mapRef.current, ev);
          setMsgs((m) => [...m, { role: "assistant", tool: "map",
            content: t("assistant.routeDrawn", lang) }]);
        } else if (ev.type === "error") {
          const key = ev.detail === "quota" ? "assistant.quota"
            : ev.detail === "badkey" ? "assistant.badkey" : "assistant.error";
          setMsgs((m) => [...m, { role: "assistant", content: t(key, lang) }]);
        }
      }
      if (!gotText) setActivity(null);
    } catch {
      setMsgs((m) => [...m, { role: "assistant", content: t("assistant.error", lang) }]);
    }
    setActivity(null);
    setBusy(false);
  };

  return (
    <div className="assistant-panel" style={{
      position: "absolute", zIndex: 11, background: "white",
      border: `1px solid ${UI.line}`, borderRadius: 10, display: "flex",
      flexDirection: "column", boxShadow: "0 4px 18px rgba(0,0,0,.18)",
    }}>
      <div style={{ padding: "8px 12px", borderBottom: `1px solid ${UI.line}`,
                    display: "flex", alignItems: "center", gap: 8 }}>
        <b style={{ color: UI.navy }}>💬 {t("assistant.title", lang)}</b>
        <span style={{ fontSize: 8, background: UI.paleBlue, color: UI.blue,
                       padding: "2px 5px", borderRadius: 3, fontWeight: 700 }}>
          {t("assistant.badge", lang)}
        </span>
        <span style={{ flex: 1 }} />
        <button onClick={onClose} style={{ border: 0, background: "none", cursor: "pointer" }}>✕</button>
      </div>
      <LlmKeySetup lang={lang} onChange={setSetup} />
      <div ref={scroller} style={{ flex: 1, overflowY: "auto", padding: 10,
                                   display: "flex", flexDirection: "column", gap: 6 }}>
        {!canSend && (
          <div style={{ color: RISK.avoid.color, fontSize: 11, lineHeight: 1.5 }}>
            {t("llm.needKey", lang)}
          </div>
        )}
        {msgs.length === 0 && (
          <div style={{ color: UI.mid, fontSize: 11, lineHeight: 1.5 }}>
            {lang === "vi"
              ? "Ví dụ: “Bây giờ đi xe máy từ chợ Thủ Đức về Linh Xuân có ổn không?” · “30 phút nữa mưa to hơn hay nhỏ hơn?”"
              : "e.g. “Is it OK to ride from Thu Duc market to Linh Xuan now?” · “Will the rain get heavier in 30 minutes?”"}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} style={{
            alignSelf: m.role === "user" ? "flex-end" : "flex-start",
            maxWidth: m.tool === "choices" ? "95%" : "85%",
            padding: m.tool === "choices" ? 0 : "6px 10px",
            borderRadius: 10, fontSize: 12,
            whiteSpace: "pre-wrap", lineHeight: 1.45,
            background: m.role === "user" ? UI.navy
              : m.tool === "choices" ? "transparent"
              : m.tool ? UI.pale : UI.paleBlue,
            color: m.role === "user" ? "white" : UI.ink,
            fontStyle: m.tool ? "italic" : "normal",
          }}>
            {m.tool === "choices" ? (
              <div style={{ fontStyle: "normal" }}>
                {m.choices?.map((c, ci) => (
                  <div key={ci} style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 11, color: UI.mid, marginBottom: 4 }}>
                      {c.options.length
                        ? t("assistant.pickOne", lang)
                        : t("assistant.pickNotFound", lang)}
                      <span style={{ fontFamily: "ui-monospace, monospace" }}>
                        {" "}“{c.query}”
                      </span>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {c.options.map((o) => (
                        <button key={o.name} disabled={busy}
                          onClick={() => send(o.name)}
                          style={{
                            textAlign: "left", background: "white",
                            border: `1px solid ${UI.line}`, borderRadius: 6,
                            padding: "6px 9px", fontSize: 12, cursor: "pointer",
                            color: UI.ink, lineHeight: 1.35,
                          }}>
                          <b>{o.name}</b>
                          {o.kind_vi && (
                            <span style={{ color: UI.mid, fontSize: 10 }}>
                              {" · "}{o.kind_vi}{o.detail ? ` · ${o.detail}` : ""}
                            </span>
                          )}
                        </button>
                      ))}
                      <button disabled={busy}
                        onClick={() => inputRef.current?.focus()}
                        style={{
                          textAlign: "left", background: UI.pale,
                          border: `1px dashed ${UI.line}`, borderRadius: 6,
                          padding: "6px 9px", fontSize: 11, cursor: "pointer",
                          color: UI.mid,
                        }}>
                        {t("assistant.pickOther", lang)}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : m.tool === "query" ? (
              <div>
                <div style={{ fontWeight: 700, fontStyle: "normal" }}>🔎 {m.content}</div>
                {m.queries?.map((q, k) => {
                  const res = resultLine(q);
                  const ev = q.evidence_class;
                  const s = ev ? (EV_STYLE[ev] ?? EV_STYLE.simulated) : null;
                  return (
                    <div key={k} style={{ fontFamily: "ui-monospace, monospace",
                                          fontSize: 10, fontStyle: "normal",
                                          color: UI.mid, marginTop: 2 }}>
                      {queryLine(q)}
                      {res && (
                        <>
                          {" → "}
                          <span style={{ color: UI.ink }}>{res}</span>{" "}
                          {s && (
                            <span style={{ background: s.bg, color: s.fg, fontSize: 8,
                                           fontWeight: 700, padding: "0 4px",
                                           borderRadius: 3 }}>
                              {t(s.key, lang)}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  );
                })}
                <div style={{ fontSize: 9, color: UI.mid, marginTop: 3,
                              fontStyle: "normal" }}>
                  {t("assistant.queryHint", lang)}
                </div>
              </div>
            ) : m.tool ? `🗺 ${m.content}` : (
              <>
                {m.content}
                {m.role === "assistant" && (
                  <EvidenceBadges evidence={m.evidence} lang={lang} />
                )}
              </>
            )}
          </div>
        ))}
        {activity && (
          <div style={{ alignSelf: "flex-start", color: UI.mid, fontSize: 11,
                        fontStyle: "italic" }}>⏳ {activity}</div>
        )}
      </div>
      <div style={{ padding: 8, borderTop: `1px solid ${UI.line}` }}>
        <div style={{ display: "flex", gap: 6 }}>
          <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void send(); }}
            placeholder={canSend ? t("assistant.placeholder", lang)
                                 : t("llm.needKey", lang)}
            disabled={busy || !canSend}
            style={{ flex: 1, border: `1px solid ${UI.line}`, borderRadius: 6,
                     padding: "7px 10px", fontSize: 12 }} />
          <button onClick={() => void send()} disabled={busy || !input.trim() || !canSend} style={{
            background: busy || !canSend ? UI.line : UI.blue, color: "white", border: 0,
            borderRadius: 6, padding: "0 14px", cursor: "pointer", fontWeight: 700,
          }}>➤</button>
        </div>
        <div style={{ fontSize: 9, color: UI.mid, marginTop: 4 }}>{t("assistant.hint", lang)}</div>
      </div>
    </div>
  );
}
