import { useRef, useState } from "react";
import { UI, RISK } from "../design/palette";
import { t, type Lang } from "../state/i18n";
import { invalidateStateCache } from "../state/store";
import { apiFetch } from "../state/api";

const CATS = ["dry", "ankle", "footrest", "wheel_hub", "impassable"] as const;
const SILHOUETTE: Record<string, string> = {
  dry: "☀️", ankle: "🦶", footrest: "🛵", wheel_hub: "🛞", impassable: "⛔",
};

/** Client-side privacy transform (I7): downsample to 64x64 and blur on a canvas.
 * The raw image never leaves the browser. */
async function blurThumb(file: File): Promise<string> {
  const img = await createImageBitmap(file);
  const c = document.createElement("canvas");
  c.width = 64; c.height = 64;
  const ctx = c.getContext("2d")!;
  ctx.filter = "blur(3px)";
  ctx.drawImage(img, 0, 0, 64, 64);
  return c.toDataURL("image/jpeg", 0.5).split(",")[1];
}

export function ReportFlow({ edgeId, tick, lang, onDone, onClose }: {
  edgeId: string; tick: number; lang: Lang; onDone: () => void; onClose: () => void;
}) {
  const [cat, setCat] = useState<string | null>(null);
  const [thumb, setThumb] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "sending" | "done" | "error">("idle");
  const fileRef = useRef<HTMLInputElement>(null);

  const send = async () => {
    if (!cat) return;
    setState("sending");
    try {
      const r = await apiFetch("/v1/observations", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          edge_id: edgeId, tick, category: cat, vehicle_context: "motorbike",
          consent: true, thumb_b64: thumb,
        }),
      });
      if (!r.ok) throw new Error(String(r.status));
      invalidateStateCache();
      setState("done");
      setTimeout(onDone, 900);
    } catch { setState("error"); }
  };

  return (
    <div style={{
      position: "absolute", bottom: 110, left: "50%", transform: "translateX(-50%)",
      zIndex: 10, background: "white", border: `1px solid ${UI.line}`, borderRadius: 10,
      padding: "12px 14px", width: "min(360px, 92vw)", fontSize: 12,
      boxShadow: "0 4px 16px rgba(0,0,0,.2)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <b style={{ color: UI.navy }}>{t("report.title", lang)}</b>
        <button onClick={onClose} style={{ border: 0, background: "none", cursor: "pointer" }}>✕</button>
      </div>
      <div style={{ color: RISK.avoid.color, fontSize: 11, margin: "4px 0" }}>
        ⚠ {t("report.hint", lang)}
      </div>
      <div style={{ color: UI.mid, fontSize: 10, marginBottom: 6 }}>{edgeId}</div>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 8 }}>
        {CATS.map((c) => (
          <button key={c} onClick={() => setCat(c)} style={{
            border: `2px solid ${cat === c ? UI.blue : UI.line}`, borderRadius: 8,
            background: cat === c ? UI.paleBlue : "white", cursor: "pointer",
            padding: "6px 8px", fontSize: 11, display: "flex", flexDirection: "column",
            alignItems: "center", minWidth: 60,
          }}>
            <span style={{ fontSize: 18 }}>{SILHOUETTE[c]}</span>
            {t(`report.${c}`, lang)}
          </button>
        ))}
      </div>
      <div style={{ marginBottom: 8 }}>
        <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }}
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (f) setThumb(await blurThumb(f));
          }} />
        <button onClick={() => fileRef.current?.click()} style={{
          border: `1px dashed ${UI.line}`, borderRadius: 6, background: UI.pale,
          padding: "5px 10px", cursor: "pointer", fontSize: 11,
        }}>📷 {t("report.photo", lang)}</button>
        {thumb && <img src={`data:image/jpeg;base64,${thumb}`} alt="blurred thumb"
                       style={{ width: 32, height: 32, marginLeft: 8, borderRadius: 4, verticalAlign: "middle" }} />}
      </div>
      <div style={{ fontSize: 9, color: UI.mid, marginBottom: 8 }}>{t("report.privacy", lang)}</div>
      <button onClick={send} disabled={!cat || state === "sending"} style={{
        width: "100%", background: cat ? UI.navy : UI.line, color: "white", border: 0,
        borderRadius: 6, padding: "8px", cursor: cat ? "pointer" : "default", fontWeight: 700,
      }}>
        {state === "done" ? "✓ " + t("report.sent", lang)
          : state === "error" ? "✕" : t("report.send", lang)}
      </button>
    </div>
  );
}
