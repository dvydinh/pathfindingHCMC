import { useState } from "react";
import { RISK, UI } from "../design/palette";
import { t, type Lang } from "../state/i18n";
import {
  clearSetup, detectModels, loadSetup, maskKey, saveSetup,
  type LlmModel, type LlmSetup,
} from "../state/llmkey";

/** Key entry -> provider detection -> model picker.
 *
 *  The provider is inferred from the key's shape rather than asked for, and the model
 *  list comes from the provider itself, filtered server-side to models that can actually
 *  call tools — the assistant is a tool-use agent, so a model that cannot call tools is
 *  not a slower option, it is a broken one.
 */
export function LlmKeySetup({ lang, onChange }: {
  lang: Lang; onChange: (s: LlmSetup | null) => void;
}) {
  const existing = loadSetup();
  const [open, setOpen] = useState(!existing);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [found, setFound] = useState<{ provider: string; label: string; models: LlmModel[] } | null>(null);
  const [setup, setSetup] = useState<LlmSetup | null>(existing);

  const detect = async () => {
    const k = key.trim();
    if (!k || busy) return;
    setBusy(true); setError(null); setFound(null);
    try {
      const res = await detectModels(k);
      setFound(res);
      const first = res.models[0];
      if (first) select(k, res.provider, res.label, first.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const select = (apiKey: string, provider: string, label: string, model: string) => {
    const s: LlmSetup = { apiKey, provider, label, model };
    saveSetup(s); setSetup(s); onChange(s);
  };

  const forget = () => {
    clearSetup(); setSetup(null); setFound(null); setKey(""); setOpen(true); onChange(null);
  };

  if (setup && !open) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10,
                    color: UI.mid, padding: "4px 10px",
                    borderBottom: `1px solid ${UI.line}` }}>
        <span style={{ background: UI.pale, color: UI.navy, padding: "1px 5px",
                       borderRadius: 3, fontWeight: 700 }}>{setup.label}</span>
        <span style={{ fontFamily: "ui-monospace, monospace" }}>{setup.model}</span>
        <span style={{ flex: 1 }} />
        <button onClick={() => setOpen(true)}
                style={{ border: 0, background: "none", color: UI.blue,
                         cursor: "pointer", fontSize: 10 }}>
          {t("llm.change", lang)}
        </button>
      </div>
    );
  }

  return (
    <div style={{ padding: "8px 10px", borderBottom: `1px solid ${UI.line}`,
                  background: UI.pale, fontSize: 11 }}>
      <div style={{ fontWeight: 700, color: UI.navy, marginBottom: 4 }}>
        🔑 {t("llm.title", lang)}
      </div>

      {setup && (
        <div style={{ marginBottom: 6, color: UI.mid, fontSize: 10 }}>
          {t("llm.current", lang)}: <b>{setup.label}</b>{" "}
          <span style={{ fontFamily: "ui-monospace, monospace" }}>
            {maskKey(setup.apiKey)}
          </span>
        </div>
      )}

      <div style={{ display: "flex", gap: 6 }}>
        <input type="password" value={key} autoComplete="off" spellCheck={false}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && detect()}
          placeholder={t("llm.placeholder", lang)} disabled={busy}
          style={{ flex: 1, border: `1px solid ${UI.line}`, borderRadius: 6,
                   padding: "6px 8px", fontSize: 11,
                   fontFamily: "ui-monospace, monospace" }} />
        <button onClick={detect} disabled={busy || !key.trim()} style={{
          background: busy || !key.trim() ? UI.line : UI.blue, color: "white",
          border: 0, borderRadius: 6, padding: "0 10px", fontWeight: 700,
          cursor: busy || !key.trim() ? "default" : "pointer", fontSize: 11,
        }}>{busy ? "…" : t("llm.detect", lang)}</button>
      </div>

      {error && (
        <div style={{ marginTop: 5, color: RISK.avoid.color, fontSize: 10, lineHeight: 1.4 }}>
          ⚠ {error}
        </div>
      )}

      {found && (
        <div style={{ marginTop: 6 }}>
          <div style={{ color: UI.mid, fontSize: 10, marginBottom: 3 }}>
            {found.label} — {found.models.length} {t("llm.modelsFound", lang)}
          </div>
          <select value={setup?.model ?? found.models[0]?.id}
            onChange={(e) => select(key.trim(), found.provider, found.label, e.target.value)}
            style={{ width: "100%", border: `1px solid ${UI.line}`, borderRadius: 6,
                     padding: "5px 6px", fontSize: 11 }}>
            {found.models.some((m) => m.recommended) && (
              <optgroup label={t("llm.recommended", lang)}>
                {found.models.filter((m) => m.recommended).map((m) => (
                  <option key={m.id} value={m.id}>{m.display_name}</option>
                ))}
              </optgroup>
            )}
            <optgroup label={t("llm.otherModels", lang)}>
              {found.models.filter((m) => !m.recommended).map((m) => (
                <option key={m.id} value={m.id}>{m.display_name}</option>
              ))}
            </optgroup>
          </select>
        </div>
      )}

      <div style={{ marginTop: 6, display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ fontSize: 9, color: UI.mid, lineHeight: 1.45, flex: 1 }}>
          {t("llm.privacy", lang)}
        </span>
        {setup && (
          <>
            <button onClick={() => setOpen(false)} style={{
              border: `1px solid ${UI.line}`, background: "white", borderRadius: 5,
              padding: "3px 8px", cursor: "pointer", fontSize: 10 }}>
              {t("llm.done", lang)}
            </button>
            <button onClick={forget} style={{
              border: 0, background: "none", color: RISK.avoid.color, cursor: "pointer",
              fontSize: 10 }}>
              {t("llm.forget", lang)}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
