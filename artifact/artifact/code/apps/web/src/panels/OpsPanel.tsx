import { useCallback, useEffect, useState } from "react";
import { UI, RISK } from "../design/palette";
import { t, type Lang } from "../state/i18n";
import { invalidateStateCache } from "../state/store";
import { apiFetch } from "../state/api";

type Feed = { feed_id: string; source_class: string; edge_id: string; status: string;
              age_s: number | null; outage: boolean; n_obs: number };
type QueueItem = { edge_id: string; score: number; expected_info: number;
                   decision_touches: number; est_p50_cm: number; safe_to_observe: boolean };

export function OpsPanel({ tick, lang, onClose, onStateChanged, onFocusEdge }: {
  tick: number; lang: Lang; onClose: () => void;
  onStateChanged: () => void; onFocusEdge: (edgeId: string) => void;
}) {
  const [feeds, setFeeds] = useState<Feed[]>([]);
  const [guards, setGuards] = useState<Record<string, number>>({});
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [closures, setClosures] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [card, setCard] = useState<Record<string, unknown> | null>(null);
  const [tab, setTab] = useState<"feeds" | "queue" | "metrics" | "card">("feeds");

  const refresh = useCallback(async () => {
    const f = await (await apiFetch(`/v1/ops/feeds?at=${tick}`)).json();
    setFeeds(f.feeds); setGuards(f.guards); setClosures(f.closures);
    const q = await (await apiFetch(`/v1/ops/queue?at=${tick}`)).json();
    setQueue(q.queue);
  }, [tick]);
  useEffect(() => { refresh(); }, [refresh]);

  const toggleOutage = async (feedId: string, active: boolean) => {
    await apiFetch("/v1/ops/outage", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feed_id: feedId, active }) });
    invalidateStateCache(); onStateChanged(); refresh();
  };
  const clearClosure = async (edgeId: string) => {
    await apiFetch("/v1/ops/closure", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edge_id: edgeId, active: false }) });
    invalidateStateCache(); onStateChanged(); refresh();
  };

  const stColor: Record<string, string> = {
    ok: RISK.low.color, stale: RISK.uncertain.color, outage: RISK.avoid.color,
    pending: UI.mid,
  };

  return (
    <div style={{
      position: "absolute", top: 0, right: 0, bottom: 0, zIndex: 12, background: "white",
      borderLeft: `1px solid ${UI.line}`, width: "min(400px, 96vw)", fontSize: 12,
      display: "flex", flexDirection: "column", boxShadow: "-4px 0 18px rgba(0,0,0,.15)",
    }}>
      <div style={{ padding: "10px 14px", borderBottom: `1px solid ${UI.line}`,
                    display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <b style={{ color: UI.navy }}>🛠 {t("ops.title", lang)}</b>
        <button onClick={onClose} style={{ border: 0, background: "none", cursor: "pointer", fontSize: 15 }}>✕</button>
      </div>
      <div style={{ display: "flex", borderBottom: `1px solid ${UI.line}` }}>
        {(["feeds", "queue", "metrics", "card"] as const).map((tb) => (
          <button key={tb} onClick={() => {
            setTab(tb);
            if (tb === "metrics" && !metrics)
              apiFetch("/v1/ops/replay-metrics").then((r) => r.json()).then(setMetrics);
            if (tb === "card" && !card)
              apiFetch("/v1/model-card").then((r) => r.json()).then(setCard);
          }} style={{
            flex: 1, border: 0, padding: "7px 4px", cursor: "pointer", fontSize: 11,
            background: tab === tb ? UI.paleBlue : "white",
            borderBottom: tab === tb ? `2px solid ${UI.blue}` : "2px solid transparent",
            fontWeight: tab === tb ? 700 : 400,
          }}>
            {tb === "feeds" ? t("ops.feeds", lang) : tb === "queue" ? "🎯"
              : tb === "metrics" ? t("ops.metrics", lang) : t("ops.modelcard", lang)}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "10px 14px" }}>
        {tab === "feeds" && (
          <>
            <div style={{ marginBottom: 8, background: UI.pale, borderRadius: 6, padding: "6px 8px" }}>
              <b>{t("ops.guards", lang)}:</b>{" "}
              {Object.entries(guards).map(([k, v]) => `${k}=${v}`).join(" · ")}
            </div>
            {closures.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <b style={{ color: RISK.avoid.color }}>{t("ops.closure", lang)}:</b>
                {closures.map((c) => (
                  <div key={c} style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 10 }}>{c}</span>
                    <button onClick={() => clearClosure(c)}
                      style={{ fontSize: 10, cursor: "pointer" }}>↩︎</button>
                  </div>
                ))}
              </div>
            )}
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead><tr style={{ color: UI.mid, textAlign: "left" }}>
                <th>feed</th><th>status</th><th>age</th><th></th></tr></thead>
              <tbody>
                {feeds.map((f) => (
                  <tr key={f.feed_id} style={{ borderTop: `1px solid ${UI.pale}` }}>
                    <td>{f.source_class === "gauge" ? "📟" : "📷"} {f.feed_id}</td>
                    <td><span style={{ color: stColor[f.status] }}>●</span> {f.status}</td>
                    <td>{f.age_s != null ? `${Math.round(f.age_s / 60)}m` : "—"}</td>
                    <td>
                      <button onClick={() => toggleOutage(f.feed_id, !f.outage)} style={{
                        fontSize: 10, cursor: "pointer", border: `1px solid ${UI.line}`,
                        borderRadius: 4, background: f.outage ? UI.paleRed : "white",
                      }}>{f.outage ? "khôi phục" : t("ops.outage", lang)}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {tab === "queue" && (
          <>
            <b>{t("ops.queue", lang)}</b>
            {queue.map((q) => (
              <div key={q.edge_id} onClick={() => onFocusEdge(q.edge_id)} style={{
                border: `1px solid ${UI.line}`, borderRadius: 6, padding: "6px 8px",
                margin: "6px 0", cursor: "pointer",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <b style={{ fontSize: 10 }}>{q.edge_id}</b>
                  <span>score {q.score}</span>
                </div>
                <div style={{ color: UI.mid, fontSize: 10 }}>
                  EIG {q.expected_info} · {q.decision_touches} route hits · ~{q.est_p50_cm} cm
                  {q.safe_to_observe ? " · ✓ an toàn để quan sát" : ""}
                </div>
              </div>
            ))}
            {queue.length === 0 && <div style={{ color: UI.mid }}>—</div>}
          </>
        )}
        {tab === "metrics" && (
          <pre style={{ fontSize: 10, whiteSpace: "pre-wrap" }}>
            {metrics ? JSON.stringify(metrics, null, 1) : "…"}
          </pre>
        )}
        {tab === "card" && (
          <pre style={{ fontSize: 10, whiteSpace: "pre-wrap" }}>
            {card ? JSON.stringify(card, null, 1) : "…"}
          </pre>
        )}
      </div>
    </div>
  );
}
