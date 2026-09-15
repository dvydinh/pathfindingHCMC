import type { Lang } from "../state/i18n";
import { t } from "../state/i18n";
import { UI } from "../design/palette";

export function EdgePopup({ props, lang, onClose }: {
  props: Record<string, unknown>; lang: Lang; onClose: () => void;
}) {
  const rows: [string, unknown][] = [
    ["ID", props.edge_id],
    [lang === "vi" ? "Loại đường" : "Road class", props.road_class],
    [lang === "vi" ? "Chiều dài (m)" : "Length (m)", props.length_m],
    [lang === "vi" ? "Cao độ tối thiểu (m)" : "Min elevation (m)", props.z_min],
    ["Sink score", props.sink_score],
    [lang === "vi" ? "Chất lượng dữ liệu" : "Data quality", props.data_quality],
  ];
  return (
    <div style={{
      position: "absolute", top: 10, left: 10, zIndex: 10, background: "white",
      border: `1px solid ${UI.line}`, borderRadius: 8, padding: "10px 12px",
      fontSize: 12, minWidth: 220, boxShadow: "0 2px 8px rgba(0,0,0,.12)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <b style={{ color: UI.navy }}>{lang === "vi" ? "Cạnh đường" : "Road edge"}</b>
        <span style={{
          fontSize: 9, background: UI.paleBlue, color: UI.blue, padding: "1px 6px",
          borderRadius: 3, fontWeight: 700,
        }}>{t("badge.inferred", lang)}</span>
        <button onClick={onClose} style={{ border: 0, background: "none", cursor: "pointer" }}>✕</button>
      </div>
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <span style={{ color: UI.mid }}>{k}</span><span>{String(v)}</span>
        </div>
      ))}
    </div>
  );
}
