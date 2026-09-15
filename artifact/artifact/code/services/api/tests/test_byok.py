"""Bring-your-own-key: provider detection, model compatibility, and credential hygiene.

The feature hands the server someone else's credential, so most of what is asserted here
is about what must *not* happen to it: not logged, not echoed, not persisted, and not
usable to make the server call an arbitrary host.
"""
import json
import re
import pytest
from conftest import needs_scenario

REAL_SHAPED = {
    "anthropic": "sk-ant-api03-" + "A" * 60,
    "openai": "sk-proj-" + "B" * 60,
    "google": "AIza" + "C" * 35,
}


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


# ---------- provider detection ----------

@pytest.mark.parametrize("provider,key", REAL_SHAPED.items())
def test_provider_detected_from_key_shape(provider, key):
    from app import llm
    assert llm.detect_provider(key) == provider


@pytest.mark.parametrize("junk", ["", "   ", "hello", "Bearer abc", "ghp_" + "x" * 36])
def test_unrecognised_keys_are_rejected_not_guessed(junk):
    from app import llm
    assert llm.detect_provider(junk) is None


def test_models_endpoint_rejects_unknown_key_shape(client):
    r = client.post("/v1/assistant/models", json={"api_key": "definitely-not-a-key"})
    assert r.status_code == 400
    assert "API key" in r.json()["detail"]


# ---------- credential hygiene ----------

@pytest.mark.parametrize("key", REAL_SHAPED.values())
def test_scrub_removes_every_supported_key_shape(key):
    from app import llm
    leaked = f"Error calling provider with Authorization: Bearer {key} (401)"
    assert key not in llm.scrub(leaked)


def test_provider_errors_are_scrubbed_before_reaching_the_client(client, monkeypatch):
    """Provider SDKs echo the Authorization header into exception strings; that string
    must never be handed back to the browser verbatim."""
    from app import llm
    key = REAL_SHAPED["openai"]

    def boom(_):
        raise RuntimeError(f"401 unauthorized for key {key}")

    monkeypatch.setattr(llm, "list_models", boom)
    r = client.post("/v1/assistant/models", json={"api_key": key})
    assert r.status_code == 502
    assert key not in r.text and "sk-***" in r.text


def test_key_is_not_accepted_in_the_request_body(client):
    """Bodies land in validation errors and access logs, so the turn endpoint must take
    the credential from a header only. An api_key in the body is ignored, not honoured."""
    r = client.post("/v1/assistant",
                    json={"message": "test", "tick": 0, "vehicle": "motorbike",
                          "api_key": REAL_SHAPED["openai"], "model": "gpt-4o-mini"})
    # No header -> falls back to server key policy; the body field buys nothing.
    assert r.status_code in (200, 503)
    if r.status_code == 503:
        assert "user key" in r.json()["detail"]


def test_turn_requires_a_model_when_a_user_key_is_supplied(client):
    r = client.post("/v1/assistant",
                    json={"message": "test", "tick": 0, "vehicle": "motorbike"},
                    headers={"X-LLM-Api-Key": REAL_SHAPED["openai"]})
    assert r.status_code == 400
    assert "Model" in r.json()["detail"]


def test_turn_rejects_an_unrecognised_user_key(client):
    r = client.post("/v1/assistant",
                    json={"message": "test", "tick": 0, "vehicle": "motorbike"},
                    headers={"X-LLM-Api-Key": "nonsense", "X-LLM-Model": "gpt-4o-mini"})
    assert r.status_code == 400


def test_no_user_supplied_base_url(client):
    """The client picks a provider, never a URL — otherwise a supplied key doubles as a
    way to make the server issue requests to an arbitrary host."""
    from app import llm
    import inspect
    src = inspect.getsource(llm.list_models) + inspect.getsource(llm.run)
    assert "base_url=" not in src or "PROVIDERS[" in src
    for cfg in llm.PROVIDERS.values():
        assert cfg["models_url"].startswith("https://")


# ---------- compatibility filtering ----------

def test_only_tool_capable_models_are_offered():
    """The assistant is a tool-use agent: a model that cannot call tools is broken here,
    not merely slower, so embeddings/audio/image models must never appear."""
    from app import llm
    body = {"data": [{"id": i} for i in [
        "gpt-4o", "gpt-4.1", "o3", "text-embedding-3-large", "whisper-1",
        "dall-e-3", "tts-1", "omni-moderation-latest", "gpt-4o-realtime-preview"]]}
    kept = [m["id"] for m in _openai_models(llm, body)]
    assert set(kept) == {"gpt-4o", "gpt-4.1", "o3"}


def test_dated_snapshots_collapse_into_their_alias():
    from app import llm
    models = [{"id": "gpt-4.1"}, {"id": "gpt-4.1-2025-04-14"},
              {"id": "gpt-9-2030-01-01"}]     # no alias -> the only way to reach it
    kept = {m["id"] for m in llm._collapse_snapshots(models)}
    assert kept == {"gpt-4.1", "gpt-9-2030-01-01"}


def test_coding_and_size_reduced_variants_are_not_recommended():
    """Recommendation is about instruction-following under strict refusal rules."""
    from app import llm
    assert llm._is_recommended("gpt-5")
    assert llm._is_recommended("claude-opus-5")
    assert not llm._is_recommended("gpt-5-codex")
    assert not llm._is_recommended("gpt-5-nano")
    assert not llm._is_recommended("claude-haiku-4-5")


def _openai_models(llm, body):
    """Exercise the same filter list_models uses, without a network call."""
    out = []
    for m in body.get("data", []):
        mid = m.get("id", "")
        if llm._OPENAI_TOOL_FAMILIES.match(mid) and not llm._OPENAI_EXCLUDE.search(mid):
            out.append({"id": mid, "display_name": mid})
    return llm._collapse_snapshots(out)


# ---------- status surface ----------

def test_status_advertises_user_key_support(client):
    """Without this the UI hides the assistant button when no server key is set, and the
    panel where a key would be entered becomes unreachable."""
    s = client.get("/v1/assistant/status").json()
    assert s["accepts_user_key"] is True
    assert {p["id"] for p in s["providers"]} == {"anthropic", "openai", "google"}
    assert all(p["key_hint"] for p in s["providers"])


@needs_scenario
def test_status_still_reports_grounding(client):
    s = client.get("/v1/assistant/status").json()
    assert s["grounding"]["gazetteer_built"] is True
    # key_hint legitimately contains "sk-…" as a placeholder, so look for key-*shaped*
    # strings rather than the prefix.
    assert not re.search(r"(sk-[A-Za-z0-9_\-]{20,}|AIza[A-Za-z0-9_\-]{20,})",
                         json.dumps(s))
