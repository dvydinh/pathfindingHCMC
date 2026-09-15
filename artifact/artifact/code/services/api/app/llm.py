"""Bring-your-own-key provider layer for the conversational assistant.

The demo ships without a usable model when no server key is configured, so a user must be
able to supply their own. That means this module handles other people's credentials, and
the rules are narrow on purpose:

  * A user key is never persisted — not to disk, not to the database, not in the scenario
    cache. It lives in the request that carries it and nowhere else.
  * A user key is never logged. Errors from providers are scrubbed before they propagate,
    because provider SDKs happily echo an Authorization header into an exception string.
  * The set of reachable hosts is fixed here. The client chooses a provider, never a URL,
    so a supplied key cannot be used to make the server call an arbitrary endpoint.

Model choice is a *compatibility* question, not a preference: the assistant is a tool-use
agent, so a model that cannot call tools cannot drive it at all. Listing therefore filters
to models that can, rather than showing everything an account can see.
"""
from __future__ import annotations
import re
import httpx

TIMEOUT = 20.0

# Fixed provider table. Detection is by key shape; the client never supplies a base URL.
PROVIDERS = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "models_url": "https://api.anthropic.com/v1/models?limit=100",
        "key_hint": "sk-ant-…",
    },
    "openai": {
        "label": "OpenAI (GPT)",
        "models_url": "https://api.openai.com/v1/models",
        "base_url": "https://api.openai.com/v1",
        "key_hint": "sk-… / sk-proj-…",
    },
    "google": {
        "label": "Google (Gemini)",
        "models_url": "https://generativelanguage.googleapis.com/v1beta/models",
        # Gemini exposes an OpenAI-compatible surface, so one tool loop serves both.
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_hint": "AIza…",
    },
}

# OpenAI accounts list embeddings, speech, image and moderation models too; none of them
# can run a tool loop. Match on family rather than an allow-list of exact ids so a newly
# released model in a known family is not hidden.
_OPENAI_TOOL_FAMILIES = re.compile(r"^(gpt-5|gpt-4\.1|gpt-4o|gpt-4-turbo|o[1-9])")
_OPENAI_EXCLUDE = re.compile(
    r"(embed|whisper|tts|audio|realtime|image|dall-e|moderation|transcribe|search|sora)")
_GOOGLE_EXCLUDE = re.compile(r"(embedding|aqa|imagen|veo|tts|native-audio|live)")
# Shown first in the picker. This job is safety-critical narration under strict refusal
# rules, so it wants strong instruction-following, not a coding or size-reduced variant.
_RECOMMENDED = re.compile(r"(opus|sonnet|^gpt-5(\.\d+)?$|^gpt-4\.1$|gemini-[0-9.]+-pro)")
_NOT_RECOMMENDED = re.compile(r"(codex|nano|mini|haiku|lite|flash-8b)")


class KeyError_(Exception):
    """Provider rejected the key, or the key is unusable. Message is always scrubbed."""


def scrub(text: str) -> str:
    """Remove anything key-shaped from a string before it is logged or returned."""
    text = re.sub(r"sk-ant-[A-Za-z0-9_\-]+", "sk-ant-***", text)
    text = re.sub(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}", "sk-***", text)
    text = re.sub(r"AIza[A-Za-z0-9_\-]{20,}", "AIza***", text)
    return text


def detect_provider(api_key: str) -> str | None:
    k = (api_key or "").strip()
    if k.startswith("sk-ant-"):
        return "anthropic"
    if k.startswith("AIza"):
        return "google"
    if k.startswith("sk-"):
        return "openai"
    return None


_SNAPSHOT = re.compile(r"^(.*)-\d{4}-\d{2}-\d{2}$")


def _collapse_snapshots(models: list[dict]) -> list[dict]:
    """Hide dated snapshots when the rolling alias is also available.

    An account can list dozens of pinned dates for one family; showing them turns the
    picker into a wall of near-identical rows and buries the model a user actually wants.
    A snapshot with no alias is kept, because then it is the only way to reach it.
    """
    ids = {m["id"] for m in models}
    out = []
    for m in models:
        base = _SNAPSHOT.match(m["id"])
        if base and base.group(1) in ids:
            continue
        out.append(m)
    return out


def _is_recommended(model_id: str) -> bool:
    return bool(_RECOMMENDED.search(model_id)) and not _NOT_RECOMMENDED.search(model_id)


def _rank(model_id: str) -> tuple:
    return (0 if _is_recommended(model_id) else 1, model_id)


def list_models(api_key: str) -> dict:
    """Ask the provider what this key can use, keeping only tool-capable models.

    Returns {provider, label, models: [{id, display_name, recommended}]}.
    Raises KeyError_ with a scrubbed message on any auth or transport failure.
    """
    provider = detect_provider(api_key)
    if provider is None:
        raise KeyError_("Không nhận ra dạng API key. Hỗ trợ: "
                        + ", ".join(f"{p['label']} ({p['key_hint']})"
                                    for p in PROVIDERS.values()))
    cfg = PROVIDERS[provider]
    try:
        if provider == "anthropic":
            r = httpx.get(cfg["models_url"], timeout=TIMEOUT,
                          headers={"x-api-key": api_key,
                                   "anthropic-version": "2023-06-01"})
        elif provider == "openai":
            r = httpx.get(cfg["models_url"], timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {api_key}"})
        else:
            r = httpx.get(cfg["models_url"], timeout=TIMEOUT,
                          headers={"x-goog-api-key": api_key})
    except Exception as ex:
        raise KeyError_(f"Không gọi được nhà cung cấp: {scrub(str(ex))}") from None

    if r.status_code in (401, 403):
        raise KeyError_("Key bị từ chối (401/403). Kiểm tra lại key hoặc quyền của nó.")
    if r.status_code >= 400:
        raise KeyError_(f"Nhà cung cấp trả lỗi {r.status_code}: {scrub(r.text[:200])}")

    body = r.json()
    models: list[dict] = []
    if provider == "anthropic":
        for m in body.get("data", []):
            mid = m.get("id", "")
            if mid.startswith("claude"):        # every Claude model supports tool use
                models.append({"id": mid, "display_name": m.get("display_name") or mid})
    elif provider == "openai":
        for m in body.get("data", []):
            mid = m.get("id", "")
            if _OPENAI_TOOL_FAMILIES.match(mid) and not _OPENAI_EXCLUDE.search(mid):
                models.append({"id": mid, "display_name": mid})
    else:
        for m in body.get("models", []):
            mid = m.get("name", "").removeprefix("models/")
            methods = m.get("supportedGenerationMethods") or []
            if (mid.startswith("gemini") and "generateContent" in methods
                    and not _GOOGLE_EXCLUDE.search(mid)):
                models.append({"id": mid, "display_name": m.get("displayName") or mid})

    models = _collapse_snapshots(models)
    models.sort(key=lambda m: _rank(m["id"]))
    for m in models:
        m["recommended"] = _is_recommended(m["id"])
    if not models:
        raise KeyError_("Key hợp lệ nhưng không có model nào gọi được tool. "
                        "Trợ lý cần tool-use, nên không dùng được key này.")
    return {"provider": provider, "label": cfg["label"], "models": models}


# --------------------------------------------------------------------------------------
# Tool loops. Each yields ("text", str) or ("tool", name) so the SSE layer is unchanged.
# --------------------------------------------------------------------------------------

def _openai_schema(tool) -> dict:
    d = tool.to_dict()
    schema = dict(d["input_schema"])
    schema.pop("title", None)
    return {"type": "function", "function": {
        "name": d["name"], "description": d["description"], "parameters": schema}}


def run_openai_compatible(api_key: str, provider: str, model: str, system: str,
                          messages: list, tools: list, max_rounds: int = 8):
    """Chat-completions tool loop. Serves OpenAI and Gemini's OpenAI-compatible surface."""
    import json
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=PROVIDERS[provider]["base_url"],
                    timeout=TIMEOUT * 3, max_retries=1)
    schemas = [_openai_schema(t) for t in tools]
    byname = {t.to_dict()["name"]: t for t in tools}
    convo = [{"role": "system", "content": system}] + messages
    for _ in range(max_rounds):
        r = client.chat.completions.create(model=model, messages=convo,
                                           tools=schemas, temperature=0)
        m = r.choices[0].message
        convo.append(m.model_dump(exclude_none=True))
        if m.content and m.content.strip():
            yield "text", m.content
        if not m.tool_calls:
            return
        for tc in m.tool_calls:
            yield "tool", tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = byname[tc.function.name].call(args)
            except Exception as ex:
                result = json.dumps({"error": scrub(str(ex))[:200]}, ensure_ascii=False)
            convo.append({"role": "tool", "tool_call_id": tc.id, "content": result})


def run_anthropic(api_key: str, model: str, system: str, messages: list, tools: list):
    """Anthropic tool runner, with the server-side refusal fallbacks when available."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    kwargs = dict(model=model, max_tokens=2000,
                  system=[{"type": "text", "text": system,
                           "cache_control": {"type": "ephemeral"}}],
                  tools=tools, messages=messages)
    try:
        runner = client.beta.messages.tool_runner(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        it = iter(runner)
        message = next(it, None)
    except Exception:
        runner = client.beta.messages.tool_runner(**kwargs)
        it = iter(runner)
        message = next(it, None)
    while message is not None:
        for block in message.content:
            if block.type == "text" and block.text.strip():
                yield "text", block.text
            elif block.type == "tool_use":
                yield "tool", block.name
        message = next(it, None)


def run(provider: str, api_key: str, model: str, system: str, messages: list, tools: list):
    if provider == "anthropic":
        yield from run_anthropic(api_key, model, system, messages, tools)
    elif provider in ("openai", "google"):
        yield from run_openai_compatible(api_key, provider, model, system, messages, tools)
    else:
        raise KeyError_(f"Nhà cung cấp không hỗ trợ: {provider}")
