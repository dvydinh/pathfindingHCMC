/** Where the API lives.
 *
 *  Every call in this client is written as a root-relative `/v1/...` path, which works in
 *  development because Vite proxies it. That silently ties the build to being served from
 *  the same origin as the API — a static deploy (GitHub Pages, S3, any CDN) with the API
 *  hosted elsewhere would issue every request to the wrong host and fail.
 *
 *  `VITE_API_BASE` is the escape hatch: set it at build time and every call is prefixed.
 *  Left unset, behaviour is exactly as before, so development and Docker are untouched.
 */
const RAW_BASE = (import.meta.env.VITE_API_BASE ?? "").trim();

/** Trailing slashes would produce `//v1/...`, which some hosts treat as a distinct path. */
export const API_BASE = RAW_BASE.replace(/\/+$/, "");

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(apiUrl(path), init);
}
