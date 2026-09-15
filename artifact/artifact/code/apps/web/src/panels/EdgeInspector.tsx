import { useEffect, useState } from "react";
import { UI, RISK, type RiskBand } from "../design/palette";
import { t, type Lang } from "../state/i18n";
import { fetchEdgeDetail, type EdgeDetail } from "../state/store";

const SRC_ICON: Record<string, string> = {
  gauge: "📟", camera: "📷", community: "🧍", official: "🏛", fleet: "🛵", simulation: "🧪",
};

export function EdgeInspector({ edgeId, tick, vehicle, lang, onClose, onReport, onCloseRoad }: {
  edgeId: string; tick: number; vehicle: string; lang: Lang; onClose: () => void;
  onReport?: (edgeId: string) => void; onCloseRoad?: (edgeId: string) => void;
}) {
  const [d, setD] = useState<EdgeDetail | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    setD(null); setErr(false);
    fetchEdgeDetail(edgeId, tick, vehicle).then(setD).catch(() => setErr(true));
  }, [edgeId, tick, vehicle]);

  return (
    <div className="edge-inspector" style={{
      position: "absolute", zIndex: 9, background: "white",
      border: `1px solid ${UI.line}`, borderRadius: 8, padding: "10px 12px",
      width: "min(300px, 88vw)", fontSize: 12, boxShadow: "0 2px 12px rgba(0,0,0,.15)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <b style={{ color: UI.navy }}>{t("inspector.title", lang)}</b>
        <span style={{ fontSize: 9, background: UI.paleAmber, color: "#8a6d1a",
                       padding: "1px 6px", borderRadius: 3, fontWeight: 700 }}>
          {t("badge.simulated", lang)}
        </span>
        <button onClick={onClose} style={{ border: 0, background: "none", cursor: "pointer" }}>✕</button>
      </div>
      <div style={{ color: UI.mid, fontSize: 10, marginBottom: 6 }}>{edgeId}</div>
      {err && <div style={{ color: RISK.avoid.color }}>—</div>}
      {!d && !err && <div style={{ color: UI.mid }}>…</div>}
      {d && (
        <>
          <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
            <span style={{
              background: RISK[(d.risk_band as RiskBand)]?.color ?? UI.mid, color: "white",
              borderRadius: 4, padding: "2px 8px", fontWeight: 700, fontSize: 11,
            }}>{t(`band.${d.risk_band}`, lang)}</span>
            <span>{t("inspector.pi", lang)}: <b>{(d.pi * 100).toFixed(0)}%</b></span>
          </div>
          <FanChart fan={d.fan} tick={tick} lang={lang} />
          <div style={{ marginTop: 6 }}>
            {t("inspector.depth", lang)}: <b>{d.depth_q.p50} cm</b>
            <span style={{ color: UI.mid }}> (±{Math.round(d.depth_q.width / 2)} cm)</span>
          </div>
          <div>
            {t("inspector.age", lang)}:{" "}
            {d.evidence_age_s >= 0
              ? <b>{Math.round(d.evidence_age_s / 60)} {lang === "vi" ? "phút" : "min"}</b>
              : <i style={{ color: UI.mid }}>{t("inspector.noObs", lang)}</i>}
          </div>
          <div style={{ margin: "4px 0" }}>
            {t("inspector.sources", lang)}:{" "}
            {Object.entries(d.source_mix).length === 0
              ? <i style={{ color: UI.mid }}>—</i>
              : Object.entries(d.source_mix).map(([k, v]) => (
                  <span key={k} style={{ marginRight: 8 }}>{SRC_ICON[k] ?? "•"}×{v}</span>
                ))}
          </div>
          <div>
            <b style={{ color: UI.navy }}>{t("inspector.reasons", lang)}</b>
            {d.reason_codes.map((r) => (
              <div key={r} style={{ color: UI.ink }}>· {t(`reason.${r}`, lang)}</div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            {onReport && (
              <button onClick={() => onReport(edgeId)} style={{
                flex: 1, background: UI.blue, color: "white", border: 0, borderRadius: 6,
                padding: "6px", cursor: "pointer", fontSize: 11, fontWeight: 600,
              }}>📢 {lang === "vi" ? "Báo cáo tại đây" : "Report here"}</button>
            )}
            {onCloseRoad && (
              <button onClick={() => onCloseRoad(edgeId)} style={{
                flex: 1, background: "white", color: RISK.avoid.color,
                border: `1px solid ${RISK.avoid.color}`, borderRadius: 6,
                padding: "6px", cursor: "pointer", fontSize: 11, fontWeight: 600,
              }}>🚧 {lang === "vi" ? "Đóng đường (CQ)" : "Close (official)"}</button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function FanChart({ fan, tick, lang }: {
  fan: { tick: number; p10: number; p50: number; p90: number }[]; tick: number; lang: Lang;
}) {
  const W = 260, H = 80, PAD = 4;
  const maxD = Math.max(20, ...fan.map((f) => f.p90));
  const maxT = fan[fan.length - 1]?.tick ?? 1;
  const x = (t_: number) => PAD + (t_ / maxT) * (W - 2 * PAD);
  const y = (d: number) => H - PAD - (d / maxD) * (H - 2 * PAD);
  const line = (key: "p10" | "p50" | "p90") =>
    fan.map((f, i) => `${i ? "L" : "M"}${x(f.tick).toFixed(1)},${y(f[key]).toFixed(1)}`).join(" ");
  const band = fan.map((f, i) => `${i ? "L" : "M"}${x(f.tick).toFixed(1)},${y(f.p90).toFixed(1)}`).join(" ")
    + fan.slice().reverse().map((f) => `L${x(f.tick).toFixed(1)},${y(f.p10).toFixed(1)}`).join(" ") + "Z";
  return (
    <svg width={W} height={H} style={{ background: UI.pale, borderRadius: 4 }}
         role="img" aria-label={lang === "vi" ? "Biểu đồ độ sâu theo thời gian" : "Depth over time"}>
      <path d={band} fill="#31B7BC33" stroke="none" />
      <path d={line("p50")} fill="none" stroke={UI.cyan} strokeWidth={2} />
      <line x1={x(tick)} x2={x(tick)} y1={PAD} y2={H - PAD} stroke={UI.navy}
            strokeDasharray="3 2" strokeWidth={1} />
      <text x={W - PAD} y={12} textAnchor="end" fontSize={9} fill={UI.mid}>{maxD.toFixed(0)} cm</text>
    </svg>
  );
}
