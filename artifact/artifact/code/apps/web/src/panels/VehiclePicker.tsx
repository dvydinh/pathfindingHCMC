import { UI } from "../design/palette";
import { t, type Lang } from "../state/i18n";

const VEHICLES = ["motorbike", "e_2w", "car", "response"] as const;
export type Vehicle = (typeof VEHICLES)[number];
const ICON: Record<Vehicle, string> = { motorbike: "🛵", e_2w: "⚡", car: "🚗", response: "🚑" };

export function VehiclePicker({ vehicle, lang, onChange }: {
  vehicle: Vehicle; lang: Lang; onChange: (v: Vehicle) => void;
}) {
  return (
    <div className="vehicle-picker" style={{
      position: "absolute", top: 10, left: "50%", transform: "translateX(-50%)", zIndex: 6,
      background: "white", border: `1px solid ${UI.line}`, borderRadius: 8,
      display: "flex",
    }}>
      {VEHICLES.map((v) => (
        <button key={v} onClick={() => onChange(v)} title={t(`vehicle.${v}`, lang)}
          aria-label={t(`vehicle.${v}`, lang)} style={{
          border: "none", padding: "7px 12px", cursor: "pointer", fontSize: 13,
          background: v === vehicle ? UI.paleBlue : "white",
          borderBottom: v === vehicle ? `2px solid ${UI.blue}` : "2px solid transparent",
          fontWeight: v === vehicle ? 700 : 400, color: UI.ink,
        }}>
          {ICON[v]} <span className="vehicle-label" style={{ fontSize: 11 }}>{t(`vehicle.${v}`, lang)}</span>
        </button>
      ))}
    </div>
  );
}
