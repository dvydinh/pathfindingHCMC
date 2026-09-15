import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { t, type Lang } from "../state/i18n";
import { UI } from "../design/palette";
import { SCENE } from "../state/store";
import { apiFetch, apiUrl } from "../state/api";

export type SceneMeta = {
  scene: string; name: string; bbox: [number, number, number, number];
  scenario: string; n_edges: number;
};

const CLASS_WIDTH: Record<string, number> = {
  motorway: 3.5, trunk: 3.2, primary: 3, secondary: 2.4, tertiary: 2,
  unclassified: 1.4, residential: 1.2, living_street: 1, service: 0.9,
  path: 0.7, track: 0.8, footway: 0.6, cycleway: 0.7,
};

export function MapView({
  lang, coverage, onEdgeClick, onReady, onEdges, onMapClick, armingRef,
}: {
  lang: Lang;
  coverage: boolean;
  onEdgeClick?: (props: Record<string, unknown>) => void;
  onReady?: (map: maplibregl.Map, scene: SceneMeta) => void;
  onEdges?: (edgeIds: string[]) => void;
  onMapClick?: (lngLat: [number, number]) => void;
  armingRef?: { current: boolean };
}) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [scene, setScene] = useState<SceneMeta | null>(null);
  const cbRef = useRef({ onEdgeClick, onMapClick });
  cbRef.current = { onEdgeClick, onMapClick };

  useEffect(() => {
    if (!el.current || mapRef.current) return;
    let cancelled = false;
    (async () => {
      const meta: SceneMeta = await (await apiFetch(`/v1/scene?scene=${SCENE}`)).json();
      if (cancelled || !el.current) return;
      setScene(meta);
      const map = new maplibregl.Map({
        container: el.current,
        style: "/basemap/style.json",
        bounds: [[meta.bbox[0], meta.bbox[1]], [meta.bbox[2], meta.bbox[3]]],
        fitBoundsOptions: { padding: 20 },
        attributionControl: false,
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      map.on("load", () => {
        map.addSource("edges", {
          type: "geojson",
          data: apiUrl(`/v1/edges.geojson?scene=${SCENE}`),
          promoteId: "edge_id",
        });
        // base casing: the road graph IS the basemap (DECISIONS 004)
        map.addLayer({
          id: "edges-base", type: "line", source: "edges",
          paint: {
            "line-color": "#B9C6CE",
            "line-width": ["+", 1, ["coalesce", ["get", "class_w"], 1]],
          },
        });
        map.setPaintProperty("edges-base", "line-width", [
          "match", ["get", "road_class"],
          ...Object.entries(CLASS_WIDTH).flat(), 1,
        ]);
        // OSM attribute completeness overlay (toggle). Added AFTER the state layer
        // below, because drawn underneath it was almost entirely hidden.
        // dynamic state layer (M2+): coloured via feature-state
        map.addLayer({
          id: "edges-state", type: "line", source: "edges",
          paint: {
            "line-color": [
              "match", ["coalesce", ["feature-state", "band"], "none"],
              "low", "#158467", "uncertain", "#E3A018",
              "avoid", "#C6483D", "unknown", "#62727F",
              "rgba(0,0,0,0)",
            ],
            "line-width": [
              "match", ["coalesce", ["feature-state", "band"], "none"],
              "avoid", 3.5, "uncertain", 2.5, "low", 2, "unknown", 1.5, 0,
            ],
            "line-dasharray": [1, 0],
          },
        });
        // Completeness of the two OSM tags that feed the passability envelope (width,
        // surface): 0.50 = neither, 0.75 = one, 1.00 = both. Three discrete classes, so
        // it is drawn with three steps rather than a continuous ramp that would imply
        // resolution the field does not have. The palette is deliberately unlike the
        // risk palette: sharing red/amber/green made an attribute-completeness layer
        // read as a safety judgement.
        map.addLayer({
          id: "edges-coverage", type: "line", source: "edges",
          layout: { visibility: "none" },
          paint: {
            "line-color": ["step", ["coalesce", ["get", "data_quality"], 0.5],
              "#6B4FA8", 0.74, "#9B8FD4", 0.99, "#D8D3EE"],
            "line-width": ["step", ["coalesce", ["get", "data_quality"], 0.5],
              2.6, 0.74, 1.8, 0.99, 1.2],
          },
        });
        apiFetch(`/v1/edges.geojson?scene=${SCENE}`).then(r => r.json()).then((gj) => {
          onEdges?.(gj.features.map((f: { properties: { edge_id: string } }) => f.properties.edge_id));
        });
        for (const kind of ["route-dry", "route-rec", "route-cons"]) {
          map.addSource(kind, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        }
        map.addLayer({ id: "route-cons", type: "line", source: "route-cons",
          paint: { "line-color": "#158467", "line-width": 3, "line-opacity": 0.45 } });
        map.addLayer({ id: "route-dry", type: "line", source: "route-dry",
          paint: { "line-color": "#666f76", "line-width": 3, "line-dasharray": [2, 1.6] } });
        map.addLayer({ id: "route-rec", type: "line", source: "route-rec",
          paint: { "line-color": "#1177AA", "line-width": 4.5 } });
        map.on("click", "edges-base", (ev) => {
          if (armingRef?.current) return;          // route-pin mode: let the map click win
          const f = ev.features?.[0];
          if (f && cbRef.current.onEdgeClick)
            cbRef.current.onEdgeClick(f.properties as Record<string, unknown>);
          if (f) (ev.originalEvent as MouseEvent & { _onEdge?: boolean })._onEdge = true;
        });
        map.on("click", (ev) => {
          if ((ev.originalEvent as MouseEvent & { _onEdge?: boolean })._onEdge) return;
          cbRef.current.onMapClick?.([ev.lngLat.lng, ev.lngLat.lat]);
        });
        map.on("mouseenter", "edges-base", () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", "edges-base", () => (map.getCanvas().style.cursor = ""));
        onReady?.(map, meta);
      });
      mapRef.current = map;
    })();
    return () => { cancelled = true; mapRef.current?.remove(); mapRef.current = null; };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("edges-coverage")) {
      map.setLayoutProperty("edges-coverage", "visibility", coverage ? "visible" : "none");
      // The risk layer is wider and always on; without dimming it, the overlay is
      // technically visible and practically unreadable.
      if (map.getLayer("edges-state"))
        map.setPaintProperty("edges-state", "line-opacity", coverage ? 0.22 : 1);
    }
  }, [coverage]);

  return (
    <div ref={el} style={{ position: "absolute", inset: 0 }}>
      {!scene && (
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center",
                      color: UI.mid, background: UI.pale }}>
          {t("app.title", lang)}…
        </div>
      )}
    </div>
  );
}
