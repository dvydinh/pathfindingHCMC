/** Risk palette — CVD-safe, never colour-only (PLAN.md §6.2).
 *  Each band carries colour + dash pattern + label; UI must render all three. */
export const RISK = {
  low:       { color: "#158467", dash: [1, 0],   labelKey: "band.low" },
  uncertain: { color: "#E3A018", dash: [2, 1.5], labelKey: "band.uncertain" },
  avoid:     { color: "#C6483D", dash: [1, 0],   labelKey: "band.avoid" },
  unknown:   { color: "#62727F", dash: [0.5, 2], labelKey: "band.unknown" },
} as const;
export type RiskBand = keyof typeof RISK;

export const UI = {
  navy: "#103B5C", blue: "#1177AA", cyan: "#31B7BC", ink: "#25313C",
  mid: "#62727F", pale: "#EDF5F7", paleBlue: "#EAF2F8", line: "#CAD7DE",
  paleAmber: "#FFF6DD", paleRed: "#FCEBE9",
} as const;
