import { useEffect, useState } from "react";
import type maplibregl from "maplibre-gl";
import { RISK, UI } from "../design/palette";
import { t, type Lang } from "../state/i18n";
import { apiFetch } from "../state/api";

type Station = {
  osm_id: string; name: string; operator: string; capacity: string;
  sockets: string[]; lon: number; lat: number; in_scene: boolean;
  km_from_scene_centre: number; bearing_from_scene_vi: string;
  routing_available?: boolean;
  access?: {
    access_known: boolean; risk_band?: string; risk_band_vi?: string;
    pi_passable?: number; access_street?: string; nearest_road_m?: number;
  };
};
type Payload = {
  n_in_scene: number; n_usable_now: number; stations: Station[];
  nearest_outside_scene: Station[]; buffer_km: number;
  no_station_mapped_in_scene: boolean; coverage_note: string;
  source: { name?: string; licence?: string };
  location_evidence_class: string; access_evidence_class: string;
};

const SRC = "charging-src";
const LAYER = "charging-pt";

/** Charging stations, with the flood layer's verdict on their approach.
 *
 *  The empty state is the important one here and is deliberately loud: OSM maps no
 *  station inside either demo bbox, so an unqualified empty map would read as "nowhere to
 *  charge". Absence of data is not data of absence, and the panel says so before it says
 *  anything else.
 */
export function ChargingPanel({ tick, vehicle, scene, lang, mapRef, onClose }: {
  tick: number; vehicle: string; scene: string; lang: Lang;
  mapRef: { current: maplibregl.Map | null }; onClose: () => void;
}) {
  const [data, setData] = useState<Payload | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    apiFetch(`/v1/charging?at=${tick}&vehicle=${vehicle}&scene=${scene}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => { if (alive) { setData(d); setErr(false); } })
      .catch(() => { if (alive) setErr(true); });
    return () => { alive = false; };
  }, [tick, vehicle, scene]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !data) return;
    const feats = data.stations.map((s) => ({
      type: "Feature" as const,
      properties: {
        color: s.access?.access_known
          ? (RISK[(s.access.risk_band ?? "unknown") as keyof typeof RISK]?.color ?? UI.mid)
          : UI.mid,
      },
      geometry: { type: "Point" as const, coordinates: [s.lon, s.lat] },
    }));
    const gj = { type: "FeatureCollection" as const, features: feats };
    const src = map.getSource(SRC) as maplibregl.GeoJSONSource | undefined;
    if (src) { src.setData(gj); return; }
    map.addSource(SRC, { type: "geojson", data: gj });
    map.addLayer({
      id: LAYER, type: "circle", source: SRC,
      paint: {
        "circle-radius": 7, "circle-color": ["get", "color"],
        "circle-stroke-width": 2, "circle-stroke-color": "white",
      },
    });
  }, [data, mapRef]);

  useEffect(() => () => {
    const map = mapRef.current;
    if (!map) return;
    if (map.getLayer(LAYER)) map.removeLayer(LAYER);
    if (map.getSource(SRC)) map.removeSource(SRC);
  }, [mapRef]);

  return (
    <div style={{
      position: "absolute", right: 12, top: 12, zIndex: 12, width: 286,
      background: "white", border: `1px solid ${UI.line}`, borderRadius: 10,
      boxShadow: "0 4px 18px rgba(0,0,0,.14)", fontSize: 12, maxHeight: "78vh",
      display: "flex", flexDirection: "column",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 10px",
                    borderBottom: `1px solid ${UI.line}` }}>
        <b style={{ color: UI.navy }}>⚡ {t("chg.title", lang)}</b>
        <span style={{ flex: 1 }} />
        <button onClick={onClose} style={{ border: 0, background: "none", cursor: "pointer" }}>✕</button>
      </div>

      <div style={{ overflowY: "auto", padding: 10 }}>
        {err && <div style={{ color: UI.mid }}>{t("chg.unavailable", lang)}</div>}

        {data?.no_station_mapped_in_scene && (
          <div style={{ background: UI.paleAmber, borderRadius: 6, padding: "7px 9px",
                        lineHeight: 1.5, marginBottom: 8 }}>
            <b>{t("chg.noneInScene", lang)}</b>
            <div style={{ color: UI.mid, fontSize: 10, marginTop: 3 }}>
              {t("chg.absenceCaveat", lang)}
            </div>
          </div>
        )}

        {data && data.stations.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ color: UI.mid, fontSize: 10, marginBottom: 4 }}>
              {t("chg.usable", lang).replace("{a}", String(data.n_usable_now))
                                    .replace("{b}", String(data.n_in_scene))}
            </div>
            {data.stations.map((s) => (
              <div key={s.osm_id} style={{ borderTop: `1px solid ${UI.line}`,
                                           padding: "5px 0" }}>
                <b>{s.name}</b>
                <div style={{ fontSize: 10, color: UI.mid }}>
                  {s.access?.access_known
                    ? `${t("chg.approach", lang)}: ${s.access.access_street} · ${s.access.risk_band_vi} · π=${s.access.pi_passable}`
                    : t("chg.noApproach", lang)}
                </div>
              </div>
            ))}
          </div>
        )}

        {data && data.nearest_outside_scene.length > 0 && (
          <div>
            <div style={{ color: UI.mid, fontSize: 10, marginBottom: 4 }}>
              {t("chg.nearestOutside", lang).replace("{km}", String(data.buffer_km))}
            </div>
            {data.nearest_outside_scene.map((s) => (
              <div key={s.osm_id} style={{ borderTop: `1px solid ${UI.line}`,
                                           padding: "5px 0", lineHeight: 1.4 }}>
                <b>{s.name}</b>
                {s.operator && <span style={{ color: UI.mid }}> · {s.operator}</span>}
                <div style={{ fontSize: 10, color: UI.mid }}>
                  {s.km_from_scene_centre} km {t("chg.toThe", lang)} {s.bearing_from_scene_vi}
                  {" · "}<span style={{ color: RISK.unknown.color }}>{t("chg.noRouting", lang)}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {data && (
          <div style={{ marginTop: 9, fontSize: 9, color: UI.mid, lineHeight: 1.5,
                        borderTop: `1px solid ${UI.line}`, paddingTop: 7 }}>
            {t("chg.provenance", lang)}
            <br />{data.source.name} · {data.source.licence}
          </div>
        )}
      </div>
    </div>
  );
}
