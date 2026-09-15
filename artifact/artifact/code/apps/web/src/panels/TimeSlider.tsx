import { useEffect, useRef } from "react";
import { UI } from "../design/palette";
import type { Lang } from "../state/i18n";

export function TimeSlider({ tick, maxTick, tickMinutes, playing, lang, onTick, onPlay }: {
  tick: number; maxTick: number; tickMinutes: number; playing: boolean; lang: Lang;
  onTick: (t: number) => void; onPlay: (p: boolean) => void;
}) {
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (playing) {
      timer.current = setInterval(() => {
        onTick(tick >= maxTick ? 0 : tick + 1);
      }, 700);
      return () => { if (timer.current) clearInterval(timer.current); };
    }
  }, [playing, tick, maxTick, onTick]);

  const mins = tick * tickMinutes;
  const label = `T+${String(Math.floor(mins / 60)).padStart(1, "0")}h${String(mins % 60).padStart(2, "0")}`;
  return (
    <div className="time-slider" style={{
      position: "absolute", left: "50%", transform: "translateX(-50%)",
      zIndex: 6, background: "white", border: `1px solid ${UI.line}`, borderRadius: 8,
      padding: "8px 14px", display: "flex", alignItems: "center", gap: 10,
      width: "min(560px, 92vw)", boxShadow: "0 2px 10px rgba(0,0,0,.12)",
    }}>
      <button onClick={() => onPlay(!playing)} aria-label="play" style={{
        border: `1px solid ${UI.line}`, background: UI.paleBlue, borderRadius: 6,
        width: 34, height: 30, cursor: "pointer", fontSize: 13,
      }}>{playing ? "⏸" : "▶"}</button>
      <input type="range" min={0} max={maxTick} value={tick} style={{ flex: 1 }}
             onChange={(e) => onTick(Number(e.target.value))} />
      <span style={{ fontVariantNumeric: "tabular-nums", fontSize: 13, color: UI.ink, minWidth: 62 }}>
        {label}
      </span>
      <span style={{
        fontSize: 9, background: UI.paleAmber, color: "#8a6d1a", padding: "2px 6px",
        borderRadius: 3, fontWeight: 700, letterSpacing: 0.5,
      }}>{lang === "vi" ? "MÔ PHỎNG" : "SIMULATED"}</span>
    </div>
  );
}
