import { useEffect, useRef, useState } from "react";
import type maplibregl from "maplibre-gl";
import { UI } from "../design/palette";
import { t, type Lang } from "../state/i18n";
import { SCENE } from "../state/store";
import { apiFetch } from "../state/api";

type Weather = {
  tick: number;
  rain_mm_h: { now: number; in_15m: number; in_30m: number; in_60m: number };
  tide_m: { now: number; in_60m: number };
  rain_curve: number[];
  rain_accum_mm: number;
  rain_accum_total_mm: number;
  rain_accum_next_60m_mm: number;
  local?: { n_edges: number; wet_edges: number; rising_edges: number;
            mean_depth_cm: number; max_depth_cm: number };
};

export function WeatherPanel({ tick, lang, mapRef }: {
  tick: number; lang: Lang; mapRef: { current: maplibregl.Map | null };
}) {
  const [w, setW] = useState<Weather | null>(null);
  const [open, setOpen] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = () => {
    const map = mapRef.current;
    const b = map?.getBounds();
    const bbox = b ? `&bbox=${b.getWest().toFixed(4)},${b.getSouth().toFixed(4)},${b.getEast().toFixed(4)},${b.getNorth().toFixed(4)}` : "";
    apiFetch(`/v1/weather?at=${tick}&scene=${SCENE}${bbox}`)
      .then((r) => r.json()).then(setW).catch(() => {});
  };

  useEffect(() => { refresh(); }, [tick]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const onMove = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(refresh, 400);          // debounce viewport moves
    };
    map.on("moveend", onMove);
    return () => { map.off("moveend", onMove); };
  }, [mapRef.current, tick]);

  if (!w) return null;
  const rainTrend = w.rain_mm_h.in_30m > w.rain_mm_h.now ? "↗" :
                    w.rain_mm_h.in_30m < w.rain_mm_h.now ? "↘" : "→";
  return (
    <div className="weather-panel" style={{
      position: "absolute", zIndex: 6, background: "white",
      border: `1px solid ${UI.line}`, borderRadius: 8, padding: "8px 10px",
      fontSize: 11, width: 200, boxShadow: "0 2px 8px rgba(0,0,0,.10)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <b style={{ color: UI.navy }}>🌦 {t("weather.title", lang)}</b>
        <span style={{ fontSize: 8, background: UI.paleAmber, color: "#8a6d1a",
                       padding: "1px 4px", borderRadius: 3, fontWeight: 700 }}>
          {lang === "vi" ? "MÔ PHỎNG" : "SIM"}
        </span>
        <button onClick={() => setOpen(!open)}
          style={{ border: 0, background: "none", cursor: "pointer", color: UI.mid }}>
          {open ? "−" : "+"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
        <span>💧 <b>{w.rain_mm_h.now}</b> mm/h {rainTrend}</span>
        <span title={t("wx.accumTitle", lang)}>
          🌧 <b>{w.rain_accum_mm}</b>/{w.rain_accum_total_mm} mm
        </span>
        <span>🌊 <b>{w.tide_m.now}</b> m</span>
      </div>
      {open && (
        <>
          <Sparkline curve={w.rain_curve} tick={w.tick} />
          <div style={{ display: "flex", gap: 4, marginTop: 4, flexWrap: "wrap" }}>
            {(["in_15m", "in_30m", "in_60m"] as const).map((k) => (
              <span key={k} style={{ background: UI.paleBlue, borderRadius: 4,
                                     padding: "1px 6px", fontSize: 10 }}>
                +{k.slice(3, -1)}′ <b>{w.rain_mm_h[k]}</b>
              </span>
            ))}
          </div>
          {w.local && (
            <div style={{ marginTop: 5, borderTop: `1px solid ${UI.pale}`, paddingTop: 4,
                          color: UI.ink, fontSize: 10 }}>
              {w.local.wet_edges} {t("weather.wet", lang)} · {w.local.rising_edges}{" "}
              {t("weather.rising", lang)} · {t("weather.maxDepth", lang)}{" "}
              <b>{w.local.max_depth_cm}</b> cm
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Sparkline({ curve, tick }: { curve: number[]; tick: number }) {
  const W = 180, H = 30;
  const max = Math.max(...curve, 1);
  const pts = curve.map((v, i) =>
    `${(i / (curve.length - 1)) * W},${H - (v / max) * (H - 3)}`).join(" ");
  const cx = (tick / (curve.length - 1)) * W;
  return (
    <svg width={W} height={H} style={{ marginTop: 3 }}>
      <polyline points={pts} fill="none" stroke={UI.cyan} strokeWidth={1.5} />
      <line x1={cx} x2={cx} y1={0} y2={H} stroke={UI.navy} strokeDasharray="2 2" />
    </svg>
  );
}
