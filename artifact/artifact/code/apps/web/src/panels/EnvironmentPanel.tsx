import { useEffect, useState } from "react";
import type maplibregl from "maplibre-gl";
import { UI } from "../design/palette";
import { t, type Lang } from "../state/i18n";
import {
  colorFor, drawEnv, fetchEnv, removeEnv, scaleFor,
  type EnvMetric, type EnvSnapshot,
} from "../state/environment";

const METRICS: { id: EnvMetric; key: string }[] = [
  { id: "apparent_temperature", key: "env.m.feels" },
  { id: "temperature_2m", key: "env.m.temp" },
  { id: "relative_humidity_2m", key: "env.m.humidity" },
  { id: "precipitation", key: "env.m.precip" },
  { id: "pm2_5", key: "env.m.pm25" },
  { id: "pm10", key: "env.m.pm10" },
  { id: "dust", key: "env.m.dust" },
  { id: "us_aqi", key: "env.m.aqi" },
  { id: "uv_index", key: "env.m.uv" },
];

/** Ambient conditions. Kept visually and textually apart from the flood layer: this one
 *  is measured reality on the real clock, that one is a synthetic storm on scenario
 *  ticks, and letting a viewer blur the two would undo the demo's provenance discipline. */
export function EnvironmentPanel({ scene, lang, mapRef, onClose }: {
  scene: string; lang: Lang;
  mapRef: { current: maplibregl.Map | null }; onClose: () => void;
}) {
  const [metric, setMetric] = useState<EnvMetric>("apparent_temperature");
  const [hour, setHour] = useState<number | null>(null);   // null = follow "now"
  const [snap, setSnap] = useState<EnvSnapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchEnv(scene, hour ?? 0)
      .then((s) => {
        if (!alive) return;
        // First load lands on midnight; jump to the hour nearest now, once.
        if (hour === null && s.current_hour_index !== s.hour_index) {
          setHour(s.current_hour_index);
          return;
        }
        if (hour === null) setHour(s.hour_index);
        setSnap(s); setErr(null);
      })
      .catch((e) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, [scene, hour]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && snap) drawEnv(map, snap, metric);
  }, [snap, metric, mapRef]);

  useEffect(() => () => { if (mapRef.current) removeEnv(mapRef.current); }, [mapRef]);

  const unit = snap?.units[metric] ?? "";
  const vals = (snap?.cells ?? [])
    .map((c) => c[metric])
    .filter((v): v is number => typeof v === "number");
  const lo = vals.length ? Math.min(...vals) : null;
  const hi = vals.length ? Math.max(...vals) : null;
  const { stops, colors } = scaleFor(metric);

  return (
    <div style={{
      position: "absolute", right: 12, top: 12, zIndex: 11, width: 268,
      background: "white", border: `1px solid ${UI.line}`, borderRadius: 10,
      boxShadow: "0 4px 18px rgba(0,0,0,.14)", fontSize: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                    padding: "8px 10px", borderBottom: `1px solid ${UI.line}` }}>
        <b style={{ color: UI.navy }}>🌡 {t("env.title", lang)}</b>
        <span style={{
          fontSize: 8, background: "#E3F3E9", color: "#1A7F4B",
          padding: "2px 5px", borderRadius: 3, fontWeight: 700,
        }}>{t("env.observedBadge", lang)}</span>
        <span style={{ flex: 1 }} />
        <button onClick={onClose}
                style={{ border: 0, background: "none", cursor: "pointer" }}>✕</button>
      </div>

      {err && (
        <div style={{ padding: 10, color: UI.mid, fontSize: 11, lineHeight: 1.5 }}>
          {t("env.unavailable", lang)}
        </div>
      )}

      {snap && (
        <div style={{ padding: 10 }}>
          <select value={metric} onChange={(e) => setMetric(e.target.value as EnvMetric)}
            style={{ width: "100%", border: `1px solid ${UI.line}`, borderRadius: 6,
                     padding: "5px 6px", fontSize: 12, marginBottom: 8 }}>
            {METRICS.map((m) => (
              <option key={m.id} value={m.id}>{t(m.key, lang)}</option>
            ))}
          </select>

          <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 2 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: UI.navy }}>
              {lo !== null ? (lo === hi ? lo : `${lo}–${hi}`) : "—"}
            </span>
            <span style={{ color: UI.mid }}>{unit}</span>
          </div>
          <div style={{ color: UI.mid, fontSize: 10, marginBottom: 8 }}>
            {snap.time_local.replace("T", " ")} · {snap.timezone}
          </div>

          {/* Legend: thresholds are published health/comfort bands, not this day's range. */}
          <div style={{ display: "flex", height: 8, borderRadius: 3, overflow: "hidden",
                        marginBottom: 3 }}>
            {colors.map((c) => (
              <div key={c} style={{ flex: 1, background: c }} />
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between",
                        color: UI.mid, fontSize: 9, marginBottom: 8 }}>
            {stops.map((s) => <span key={s}>{s}</span>)}
          </div>

          <div style={{ borderTop: `1px solid ${UI.line}`, paddingTop: 7 }}>
            <label style={{ color: UI.mid, fontSize: 10 }}>
              {t("env.hour", lang)} {hour === snap.current_hour_index
                ? t("env.now", lang) : `+${hour}h`}
            </label>
            <input type="range" min={0} max={Math.max(0, snap.n_hours - 1)}
              value={hour ?? snap.hour_index}
              onChange={(e) => setHour(Number(e.target.value))}
              style={{ width: "100%" }} />
          </div>

          {snap.uniform_across_scene[metric] && (
            <div style={{ marginTop: 6, fontSize: 9, color: UI.mid, lineHeight: 1.45,
                          background: UI.pale, borderRadius: 4, padding: "4px 6px" }}>
              {t("env.uniform", lang)}
            </div>
          )}
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6 }}>
            {snap.cells.map((c, i) => (
              <span key={i} style={{
                fontSize: 9, padding: "2px 5px", borderRadius: 3,
                background: colorFor(metric, c[metric] as number | null),
                color: "#123", fontWeight: 700,
              }}>{c[metric] ?? "—"}</span>
            ))}
          </div>

          <div style={{ marginTop: 8, color: UI.mid, fontSize: 9, lineHeight: 1.5 }}>
            {t("env.resolution", lang)
              .replace("{n}", String(snap.n_source_cells))
              .replace("{km}", String(snap.source_cell_span_km))}
            <br />
            {t("env.independent", lang)}
            <br />
            {snap.source.weather} · {snap.source.air_quality} · {snap.source.licence}
          </div>
        </div>
      )}
    </div>
  );
}
