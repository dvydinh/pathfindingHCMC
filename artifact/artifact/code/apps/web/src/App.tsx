import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { MapView } from "./map/MapView";
import { StateJoin } from "./map/stateJoin";
import { EdgeInspector } from "./panels/EdgeInspector";
import { TimeSlider } from "./panels/TimeSlider";
import { Legend } from "./panels/Legend";
import { VehiclePicker, type Vehicle } from "./panels/VehiclePicker";
import { RouteCompare, type RouteBundle } from "./panels/RouteCompare";
import { WeatherPanel } from "./panels/WeatherPanel";
import { ReportFlow } from "./panels/ReportFlow";
import { OpsPanel } from "./panels/OpsPanel";
import { AssistantPanel } from "./panels/AssistantPanel";
import { EnvironmentPanel } from "./panels/EnvironmentPanel";
import { ChargingPanel } from "./panels/ChargingPanel";
import { drawCoverage, fetchCoverage, removeCoverage, type SensorCoverage } from "./state/sensors";
import { checkAssistant } from "./state/assistant";
import { invalidateStateCache } from "./state/store";
import { fetchState } from "./state/store";
import { requestRoutes, drawRoutes, clearRoutes } from "./state/routing";
import { t, type Lang } from "./state/i18n";
import { SCENE } from "./state/store";
import { UI } from "./design/palette";
import { apiFetch } from "./state/api";
import { FEATURES } from "./state/features";

const MAX_TICK = 48;
const TICK_MIN = 5;

export default function App() {
  const [lang] = useState<Lang>("vi");
  const [coverage, setCoverage] = useState(false);
  const [inspected, setInspected] = useState<string | null>(null);
  const [tick, setTick] = useState(() =>
    Math.min(48, Math.max(0, Number(new URLSearchParams(location.search).get("t") ?? 0) || 0)));
  const [playing, setPlaying] = useState(false);
  const [vehicle, setVehicle] = useState<Vehicle>("motorbike");
  const [stateReady, setStateReady] = useState(false);
  const [routeMode, setRouteMode] = useState<"idle" | "collect">("idle");
  const [nPoints, setNPoints] = useState(0);
  const [bundle, setBundle] = useState<RouteBundle | null>(null);
  const [busy, setBusy] = useState(false);
  const [reporting, setReporting] = useState<string | null>(null);
  const [opsOpen, setOpsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatAvail, setChatAvail] = useState(false);
  const [envOpen, setEnvOpen] = useState(false);
  const [chgOpen, setChgOpen] = useState(false);
  const [sensorCov, setSensorCov] = useState(false);
  const [covData, setCovData] = useState<SensorCoverage | null>(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!sensorCov) { removeCoverage(map); return; }
    fetchCoverage(SCENE)
      .then((c) => { setCovData(c); if (mapRef.current) drawCoverage(mapRef.current, c); })
      .catch((e) => console.error("sensor coverage failed:", e));
  }, [sensorCov]);
  useEffect(() => { checkAssistant().then(setChatAvail); }, []);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const joinRef = useRef(new StateJoin());
  const pointsRef = useRef<[number, number][]>([]);   // origin, stops..., destination
  const armingRef = useRef(false);
  const markersRef = useRef<maplibregl.Marker[]>([]);

  const applyState = useCallback(async (tk: number, vh: Vehicle) => {
    const map = mapRef.current;
    if (!map) return;
    try {
      const st = await fetchState(tk, vh);
      joinRef.current.apply(map, st);
      setStateReady(true);
      fetchState(Math.min(tk + 1, MAX_TICK), vh);
    } catch (err) { console.error("state apply failed:", err); }
  }, []);

  useEffect(() => { applyState(tick, vehicle); }, [tick, vehicle, applyState]);

  const reroute = useCallback(async (tk: number, vh: Vehicle) => {
    const pts = pointsRef.current;
    const map = mapRef.current;
    if (pts.length < 2 || !map) return;
    setBusy(true);
    try {
      const b = await requestRoutes(pts[0], pts[pts.length - 1], tk, vh, pts.slice(1, -1));
      setBundle(b);
      drawRoutes(map, b);
    } catch (err) { console.error("route request failed:", err); setBundle(null); }
    setBusy(false);
  }, []);

  useEffect(() => { reroute(tick, vehicle); }, [tick, vehicle, reroute]);

  useEffect(() => {                      // rehearsal hook: ?route=lon1,lat1,lon2,lat2
    const q = new URLSearchParams(location.search).get("route");
    if (!q) return;
    const nums = q.split(",").map(Number);
    if (nums.length < 4 || nums.length % 2 || nums.some(Number.isNaN)) return;
    pointsRef.current = [];
    for (let i = 0; i < nums.length; i += 2) pointsRef.current.push([nums[i], nums[i + 1]]);
    const t0 = setTimeout(() => reroute(tick, vehicle), 2500);
    return () => clearTimeout(t0);
  }, [reroute]);

  const onMapClick = useCallback((ll: [number, number]) => {
    const map = mapRef.current;
    if (!map || routeMode !== "collect") return;
    const n = pointsRef.current.length;
    const color = n === 0 ? "#158467" : "#1177AA";     // origin green, stops blue
    const m = new maplibregl.Marker({ color }).setLngLat(ll).addTo(map);
    markersRef.current.push(m);
    pointsRef.current.push(ll);
    setNPoints(pointsRef.current.length);
  }, [routeMode]);

  const finishRoute = useCallback(() => {
    if (pointsRef.current.length < 2) return;
    // recolor the last marker as the destination
    const last = markersRef.current[markersRef.current.length - 1];
    if (last) {
      const ll = last.getLngLat();
      last.remove();
      markersRef.current[markersRef.current.length - 1] =
        new maplibregl.Marker({ color: "#C6483D" }).setLngLat(ll).addTo(mapRef.current!);
    }
    armingRef.current = false;
    setRouteMode("idle");
    reroute(tick, vehicle);
  }, [tick, vehicle, reroute]);

  const startRoute = () => {
    const map = mapRef.current;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
    pointsRef.current = [];
    setNPoints(0);
    setBundle(null);
    if (map) clearRoutes(map);
    armingRef.current = true;
    setRouteMode("collect");
  };

  return (
    <div className="app">
      <div className="map-wrap">
        <MapView lang={lang} coverage={coverage}
          onEdgeClick={(p) => setInspected(String(p.edge_id))}
          onReady={(m) => { mapRef.current = m; applyState(tick, vehicle); }}
          onEdges={(ids) => { joinRef.current.setEdgeIds(ids); applyState(tick, vehicle); }}
          onMapClick={onMapClick} armingRef={armingRef} />
        <VehiclePicker vehicle={vehicle} lang={lang} onChange={setVehicle} />
        <WeatherPanel tick={tick} lang={lang} mapRef={mapRef} />
        <Legend lang={lang} />
        {inspected && (
          <EdgeInspector edgeId={inspected} tick={tick} vehicle={vehicle} lang={lang}
            onClose={() => setInspected(null)}
            onReport={(e) => { setReporting(e); }}
            onCloseRoad={async (e) => {
              await apiFetch("/v1/ops/closure", { method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ edge_id: e, active: true }) });
              invalidateStateCache();
              joinRef.current.forceNext();
              applyState(tick, vehicle); reroute(tick, vehicle);
            }} />
        )}
        {reporting && (
          <ReportFlow edgeId={reporting} tick={tick} lang={lang}
            onDone={() => { setReporting(null); joinRef.current.forceNext(); applyState(tick, vehicle); reroute(tick, vehicle); }}
            onClose={() => setReporting(null)} />
        )}
        {FEATURES.charging && chgOpen && (
          <ChargingPanel tick={tick} vehicle={vehicle} scene={SCENE} lang={lang}
            mapRef={mapRef} onClose={() => setChgOpen(false)} />
        )}
        {FEATURES.environment && envOpen && (
          <EnvironmentPanel scene={SCENE} lang={lang} mapRef={mapRef}
            onClose={() => setEnvOpen(false)} />
        )}
        {chatOpen && (
          <AssistantPanel tick={tick} vehicle={vehicle} lang={lang} mapRef={mapRef}
            onClose={() => setChatOpen(false)} />
        )}
        {opsOpen && (
          <OpsPanel tick={tick} lang={lang} onClose={() => setOpsOpen(false)}
            onStateChanged={() => { joinRef.current.forceNext(); applyState(tick, vehicle); reroute(tick, vehicle); }}
            onFocusEdge={(e) => { setInspected(e); }} />
        )}
        {bundle && (
          <RouteCompare bundle={bundle} lang={lang} tickMinutes={TICK_MIN}
            onClose={() => { setBundle(null); if (mapRef.current) clearRoutes(mapRef.current); }} />
        )}
        {SCENE === "danang" && (
          <div style={{
            position: "absolute", top: 56, left: "50%", transform: "translateX(-50%)",
            zIndex: 6, background: UI.paleAmber, border: "1px solid #E3A018",
            borderRadius: 6, padding: "4px 10px", fontSize: 11, fontWeight: 700,
          }}>
            {lang === "vi" ? "CẢNH CHUYỂN GIAO — TÍNH TRƯỚC, MÔ PHỎNG, KHÔNG PHẢI DỊCH VỤ TRỰC TIẾP"
              : "TRANSFER SCENE — PRECOMPUTED, SIMULATED, NOT A LIVE SERVICE"}
          </div>
        )}
        <TimeSlider tick={tick} maxTick={MAX_TICK} tickMinutes={TICK_MIN} playing={playing}
          lang={lang} onTick={setTick} onPlay={setPlaying} />
        <div className="ctrl-left" style={{
          position: "absolute", zIndex: 5, display: "flex",
          flexDirection: "column", gap: 6,
        }}>
          <button onClick={startRoute} disabled={busy} style={{
            background: routeMode !== "idle" ? UI.paleAmber : UI.navy,
            color: routeMode !== "idle" ? UI.ink : "white",
            border: "none", borderRadius: 6, padding: "8px 12px", cursor: "pointer",
            fontSize: 13, fontWeight: 600, boxShadow: "0 1px 6px rgba(0,0,0,.2)",
          }}>
            {routeMode === "collect"
              ? (nPoints === 0 ? t("route.pickOrigin", lang) : t("route.addPoint", lang))
              : (lang === "vi" ? "🧭 Tìm đường an toàn" : "🧭 Find safe route")}
          </button>
          {routeMode === "collect" && nPoints >= 2 && (
            <button onClick={finishRoute} style={{
              background: "#158467", color: "white", border: "none", borderRadius: 6,
              padding: "8px 12px", cursor: "pointer", fontSize: 13, fontWeight: 700,
            }}>
              {t("route.finish", lang)} ({nPoints})
            </button>
          )}
          <select value={SCENE} onChange={(e) => {
            const u = new URL(location.href); u.searchParams.set("scene", e.target.value);
            location.href = u.toString();
          }} style={{
            background: "white", border: `1px solid ${UI.line}`, borderRadius: 6,
            padding: "6px 8px", fontSize: 12, cursor: "pointer",
          }}>
            <option value="thuduc">Thủ Đức (pilot)</option>
            <option value="danang">Đà Nẵng (transfer, frozen)</option>
          </select>
          <button onClick={() => setOpsOpen(true)} style={{
            background: "white", border: `1px solid ${UI.line}`, borderRadius: 6,
            padding: "6px 10px", fontSize: 12, cursor: "pointer", textAlign: "left",
          }}>🛠 {lang === "vi" ? "Vận hành" : "Operations"}</button>
          {FEATURES.environment && (
          <button onClick={() => setEnvOpen(!envOpen)} style={{
            background: envOpen ? UI.paleBlue : "white", border: `1px solid ${UI.line}`,
            borderRadius: 6, padding: "6px 10px", fontSize: 12, cursor: "pointer",
            textAlign: "left",
          }}>🌡 {lang === "vi" ? "Không khí & nhiệt" : "Air & heat"}</button>
          )}
          {FEATURES.charging && (
          <button onClick={() => setChgOpen(!chgOpen)} style={{
            background: chgOpen ? UI.paleBlue : "white", border: `1px solid ${UI.line}`,
            borderRadius: 6, padding: "6px 10px", fontSize: 12, cursor: "pointer",
            textAlign: "left",
          }}>⚡ {t("chg.button", lang)}</button>
          )}
          {chatAvail && (
            <button onClick={() => setChatOpen(!chatOpen)} style={{
              background: chatOpen ? UI.paleBlue : "white", border: `1px solid ${UI.line}`,
              borderRadius: 6, padding: "6px 10px", fontSize: 12, cursor: "pointer",
              textAlign: "left",
            }}>💬 {lang === "vi" ? "Trợ lý" : "Assistant"}</button>
          )}
          <label style={{
            background: "white", border: `1px solid ${UI.line}`, borderRadius: 6,
            padding: "5px 8px", fontSize: 11, cursor: "pointer",
          }}>
            <input type="checkbox" checked={coverage}
              onChange={(e) => setCoverage(e.target.checked)} />
            {" "}{t("cov.toggle", lang)}
            {!stateReady && <span style={{ color: UI.mid }}> · {lang === "vi" ? "chưa có kịch bản" : "no scenario"}</span>}
          </label>
          {coverage && (
            <div style={{
              background: "white", border: `1px solid ${UI.line}`, borderRadius: 6,
              padding: "6px 8px", fontSize: 9, color: UI.mid, lineHeight: 1.5,
              maxWidth: 190,
            }}>
              <b style={{ color: UI.navy, fontSize: 10 }}>{t("cov.title", lang)}</b>
              {([["#6B4FA8", "cov.none"], ["#9B8FD4", "cov.one"],
                 ["#D8D3EE", "cov.both"]] as const).map(([c, k]) => (
                <div key={k} style={{ display: "flex", alignItems: "center", gap: 5,
                                      marginTop: 3 }}>
                  <span style={{ width: 16, height: 3, background: c, borderRadius: 2,
                                 flexShrink: 0 }} />
                  <span>{t(k, lang)}</span>
                </div>
              ))}
              <div style={{ marginTop: 5 }}>{t("cov.why", lang)}</div>
              <div style={{ marginTop: 3, fontStyle: "italic" }}>{t("cov.dimmed", lang)}</div>
            </div>
          )}
          <label style={{
            background: "white", border: `1px solid ${UI.line}`, borderRadius: 6,
            padding: "5px 8px", fontSize: 11, cursor: "pointer",
          }}>
            <input type="checkbox" checked={sensorCov}
              onChange={(e) => setSensorCov(e.target.checked)} />
            {" "}{t("sensor.toggle", lang)}
            {sensorCov && covData && (
              <span style={{ color: UI.mid }}> · {covData.pct_length_covered}%</span>
            )}
          </label>
          {sensorCov && covData && (
            <div style={{
              background: "white", border: `1px solid ${UI.line}`, borderRadius: 6,
              padding: "6px 8px", fontSize: 9, color: UI.mid, lineHeight: 1.5,
              maxWidth: 190,
            }}>
              {t("sensor.summary", lang)
                .replace("{n}", String(covData.n_sensors))
                .replace("{e}", String(covData.n_edges_covered))
                .replace("{tot}", String(covData.n_edges_total))
                .replace("{p}", String(covData.pct_length_covered))}
              <br /><br />{t("sensor.model", lang)}
            </div>
          )}
        </div>
        <div className="attribution">{t("attribution", lang)}</div>
      </div>
    </div>
  );
}
