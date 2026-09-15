/** User-supplied model credentials, held for this browser tab only.
 *
 *  sessionStorage, not localStorage: a key pasted into a demo on someone else's laptop
 *  should not outlive the tab. Nothing is sent anywhere except as request headers to our
 *  own API, which forwards it to the chosen provider and never stores it.
 */
import { apiFetch } from "./api";
const STORE_KEY = "duongan.llm";

export type LlmModel = { id: string; display_name: string; recommended: boolean };
export type LlmSetup = { apiKey: string; provider: string; label: string; model: string };

export function loadSetup(): LlmSetup | null {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as LlmSetup;
    return s.apiKey && s.model ? s : null;
  } catch { return null; }
}

export function saveSetup(s: LlmSetup): void {
  try { sessionStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch { /* private mode */ }
}

export function clearSetup(): void {
  try { sessionStorage.removeItem(STORE_KEY); } catch { /* ignore */ }
}

/** Show enough of a key to recognise it, never enough to use it. */
export function maskKey(k: string): string {
  return k.length <= 12 ? "•".repeat(k.length) : `${k.slice(0, 7)}…${k.slice(-4)}`;
}

export async function detectModels(apiKey: string):
  Promise<{ provider: string; label: string; models: LlmModel[] }> {
  const r = await apiFetch("/v1/assistant/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
  return body;
}

/** Headers that carry the key. Empty when the server has its own key configured. */
export function authHeaders(): Record<string, string> {
  const s = loadSetup();
  return s ? { "X-LLM-Api-Key": s.apiKey, "X-LLM-Model": s.model } : {};
}
