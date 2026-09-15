import { RISK, UI, type RiskBand } from "../design/palette";
import { t, type Lang } from "../state/i18n";

const DASH_CSS: Record<RiskBand, string> = {
  low: "none", uncertain: "4px dashed", avoid: "none", unknown: "2px dotted",
};

export function Legend({ lang }: { lang: Lang }) {
  return (
    <div className="legend" style={{
      position: "absolute", zIndex: 6, background: "white",
      border: `1px solid ${UI.line}`, borderRadius: 8, padding: "8px 12px", fontSize: 12,
    }}>
      {(Object.keys(RISK) as RiskBand[]).map((band) => (
        <div key={band} style={{ display: "flex", alignItems: "center", gap: 8, margin: "3px 0" }}>
          <span style={{
            width: 26, height: 0,
            borderTop: band === "uncertain" ? `3px dashed ${RISK[band].color}`
              : band === "unknown" ? `3px dotted ${RISK[band].color}`
              : `4px solid ${RISK[band].color}`,
          }} />
          <span>{t(RISK[band].labelKey, lang)}</span>
        </div>
      ))}
    </div>
  );
}
