import { UI, RISK } from "../design/palette";
import { t, type Lang } from "../state/i18n";

export type RouteBundle = {
  status: string;
  n_legs?: number;
  routes: { kind: string; travel_time_s: number; risk_exposure_s: number;
            max_edge_risk: number; edge_ids: string[]; leg_times_s?: number[] }[];
  wait_suggestion: { depart_tick: number; reason: string } | null;
  comparison: { added_time_s?: number; avoided_exposure_s?: number };
  explanation: { edge_id: string; reason_code: string; detail: string }[];
};

const fmt = (s: number) => `${Math.round(s / 60)} ph ${Math.round(s % 60)} s`;

export function RouteCompare({ bundle, lang, tickMinutes, onClose }: {
  bundle: RouteBundle; lang: Lang; tickMinutes: number; onClose: () => void;
}) {
  const by = (k: string) => bundle.routes.find((r) => r.kind === k);
  const dry = by("fastest_dry"), rec = by("recommended");
  return (
    <div style={{
      position: "absolute", top: 60, right: 10, zIndex: 8, background: "white",
      border: `1px solid ${UI.line}`, borderRadius: 8, padding: "10px 14px",
      width: "min(330px, 90vw)", fontSize: 12, boxShadow: "0 2px 12px rgba(0,0,0,.15)",
      maxHeight: "70vh", overflowY: "auto",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <b style={{ color: UI.navy }}>{t("route.title", lang)}</b>
        <button onClick={onClose} style={{ border: 0, background: "none", cursor: "pointer" }}>✕</button>
      </div>
      {bundle.status === "no_safe_route" && (
        <div style={{ background: UI.paleRed, border: `1px solid ${RISK.avoid.color}`,
                      borderRadius: 6, padding: "6px 8px", marginBottom: 8 }}>
          <b style={{ color: RISK.avoid.color }}>{t("route.none", lang)}</b>
          {bundle.wait_suggestion && (
            <div style={{ marginTop: 4 }}>
              {t("route.wait", lang)}{" "}
              <b>T+{Math.floor(bundle.wait_suggestion.depart_tick * tickMinutes / 60)}h
                {String(bundle.wait_suggestion.depart_tick * tickMinutes % 60).padStart(2, "0")}</b>
            </div>
          )}
        </div>
      )}
      {dry && (
        <Row color="#888" dash label={`${t("route.dry", lang)} (${t("route.notRecommended", lang)})`}
             time={fmt(dry.travel_time_s)} risk={fmt(dry.risk_exposure_s)} />
      )}
      {rec && (
        <Row color={UI.blue} label={t("route.recommended", lang)}
             time={fmt(rec.travel_time_s)} risk={fmt(rec.risk_exposure_s)} />
      )}
      {(bundle.n_legs ?? 1) > 1 && rec?.leg_times_s && (
        <div style={{ fontSize: 10, color: UI.mid, margin: "2px 0 6px" }}>
          {bundle.n_legs} {t("route.legs", lang)}:{" "}
          {rec.leg_times_s.map((s_, i) => `${i + 1}) ${Math.round(s_ / 60)}ph`).join("  ")}
        </div>
      )}
      {dry && rec && (
        <div style={{ background: UI.paleBlue, borderRadius: 6, padding: "6px 8px", margin: "6px 0" }}>
          <div>{t("route.added", lang)}: <b>+{fmt(bundle.comparison.added_time_s ?? 0)}</b></div>
          <div>{t("route.avoided", lang)}: <b style={{ color: RISK.low.color }}>
            −{fmt(bundle.comparison.avoided_exposure_s ?? 0)}</b></div>
        </div>
      )}
      {bundle.explanation.length > 0 && (
        <>
          <b style={{ color: UI.navy }}>{t("route.why", lang)}</b>
          {bundle.explanation.slice(0, 5).map((x) => (
            <div key={x.edge_id} style={{ borderLeft: `3px solid ${RISK.uncertain.color}`,
                                          paddingLeft: 6, margin: "4px 0" }}>
              <div>{t(`reason.${x.reason_code}`, lang)}</div>
              <div style={{ color: UI.mid, fontSize: 10 }}>{x.edge_id} · {x.detail}</div>
            </div>
          ))}
        </>
      )}
      <div style={{ marginTop: 6, fontSize: 9, color: UI.mid }}>
        {lang === "vi"
          ? "Tuyến ít rủi ro hơn không phải là bảo đảm an toàn. Dữ liệu mô phỏng."
          : "A lower-risk route is not a safety guarantee. Simulated data."}
      </div>
    </div>
  );
}

function Row({ color, label, time, risk, dash }: {
  color: string; label: string; time: string; risk: string; dash?: boolean;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "4px 0" }}>
      <span style={{ width: 22, borderTop: dash ? `3px dashed ${color}` : `4px solid ${color}` }} />
      <div style={{ flex: 1 }}>
        <div>{label}</div>
        <div style={{ color: "#62727F", fontSize: 10 }}>⏱ {time} · ⚠ {risk}</div>
      </div>
    </div>
  );
}
