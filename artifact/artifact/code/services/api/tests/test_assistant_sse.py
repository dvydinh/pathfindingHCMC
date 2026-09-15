"""End-to-end assertions on the assistant's SSE stream.

Every other assistant test calls the tools directly. That proves the engine layer refuses
an unknown place, but it says nothing about the bytes a user actually receives, because
the final wording is authored by the model. These tests drive the whole endpoint with a
stubbed LLM so the stream itself can be asserted on: what reaches the browser, not what
the tool returned.

The stub never contacts a provider. It stands in for ``llm.run`` and yields the same
``("text", str) | ("tool", name)`` pairs the real loop yields, calling the real tools in
between so the real gazetteer decides what is found and what is refused.
"""
import json
import re

import pytest
from conftest import needs_scenario, needs_feature

pytestmark = [needs_scenario, needs_feature("assistant")]

# Any depth-like number reaching the user. The failure this guards against is a reply
# that invents "khoảng 15cm" for a street the gazetteer never resolved.
DEPTH_PATTERN = re.compile(r"\d+\s*(cm|centimet|xentimet)", re.IGNORECASE)
REFUSAL_WORDS = ("không tìm thấy", "không có địa điểm", "ngoài phạm vi",
                 "không có trong", "không nằm trong")

FAKE_PLACE = "Đường Không Có Thật XYZ"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _tools_by_name(tools):
    out = {}
    for t in tools:
        schema = t.to_dict() if hasattr(t, "to_dict") else dict(t)
        out[schema.get("name") or getattr(t, "name", None)] = t
    return out


def _install_stub(monkeypatch, script):
    """Replace llm.run with a scripted loop that still exercises the real tools.

    Args:
        script: callable(tools_by_name) -> iterable of ("text"|"tool", value) pairs.
    """
    from app.routers import assistant

    def fake_run(provider, api_key, model, system, messages, tools):
        yield from script(_tools_by_name(tools))

    monkeypatch.setattr(assistant.llm, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    assistant._client = object()          # bypass the availability gate
    return assistant


def _collect(resp):
    """Parse an SSE response into (list of (event, data), full raw text)."""
    events, raw = [], resp.text
    event = None
    for line in raw.splitlines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: ") and event:
            events.append((event, json.loads(line[6:])))
    return events, raw


@needs_scenario
def test_assistant_refuses_unknown_place(client, monkeypatch):
    """A made-up street must produce a refusal and no depth number at all.

    This is the whole anti-hallucination claim reduced to one assertion on the wire: the
    gazetteer refused, so nothing downstream may present a measurement.
    """
    def script(tools):
        # The model does what the system prompt tells it to: resolve the name first.
        out = json.loads(tools["find_place"].call({"query": FAKE_PLACE}))
        assert out["status"] == "not_found"
        yield "tool", "find_place"
        yield "text", ("Mình không tìm thấy địa điểm này trong vùng demo Thủ Đức. "
                       "Bạn nói lại tên giúp mình, hoặc chỉ điểm trên bản đồ nhé.")

    assistant = _install_stub(monkeypatch, script)
    try:
        r = client.post("/v1/assistant", json={
            "message": f"{FAKE_PLACE} ngập chưa?", "tick": 22, "vehicle": "motorbike"})
        assert r.status_code == 200
        events, raw = _collect(r)

        texts = " ".join(d["text"] for e, d in events if e == "text")
        assert texts, "no answer text reached the client"

        # 1. no depth number anywhere in the stream the user sees
        assert not DEPTH_PATTERN.search(texts), \
            f"a refusal answer quoted a depth: {texts!r}"

        # 2. the answer actually refuses
        assert any(w in texts.lower() for w in REFUSAL_WORDS), \
            f"answer does not refuse clearly: {texts!r}"

        # 3. the router never ran, and the trace says so
        queries = [d for e, d in events if e == "query"]
        assert queries, "no query trace was streamed"
        ops = [(q["op"], q["status"]) for q in queries[0]["queries"]]
        assert ("find_place", "not_found") in ops
        assert not any(op == "plan_route" and st == "executed" for op, st in ops), \
            "a refused place still reached the router"

        # 4. no route geometry was streamed
        assert not [e for e, _ in events if e == "routes"]
    finally:
        assistant._client = None


@needs_scenario
def test_answer_carries_a_provenance_label(client, monkeypatch):
    """A reply built on engine values must arrive labelled with where they came from."""
    def script(tools):
        json.loads(tools["find_place"].call({"query": "Kha Vạn Cân"}))
        yield "tool", "find_place"
        st = json.loads(tools["get_street_state"].call(
            {"street_name": "Kha Vạn Cân", "tick": 22, "vehicle": "motorbike"}))
        assert "evidence_class" in st
        yield "tool", "get_street_state"
        yield "text", "Tuyến này đang có đoạn xấu, bạn cân nhắc đi đường khác nhé."

    assistant = _install_stub(monkeypatch, script)
    try:
        r = client.post("/v1/assistant", json={
            "message": "Kha Vạn Cân ngập chưa?", "tick": 22, "vehicle": "motorbike"})
        events, _ = _collect(r)

        text_events = [d for e, d in events if e == "text"]
        assert text_events, "no answer text"
        assert text_events[-1]["evidence"], "answer arrived with no provenance label"
        assert set(text_events[-1]["evidence"]) <= {"observed", "inferred", "simulated"}
        # the gazetteer hit is real-world data, the depths are not — both must show
        assert "observed" in text_events[-1]["evidence"]
        assert "simulated" in text_events[-1]["evidence"]
    finally:
        assistant._client = None


@needs_scenario
def test_every_surfaced_number_carries_its_label(client, monkeypatch):
    """No trace entry may show engine values without an evidence_class beside them."""
    def script(tools):
        json.loads(tools["get_street_state"].call(
            {"street_name": "Kha Vạn Cân", "tick": 22, "vehicle": "motorbike"}))
        yield "tool", "get_street_state"
        json.loads(tools["get_area_weather"].call({"tick": 22}))
        yield "tool", "get_area_weather"
        yield "text", "Đây là tình hình hiện tại."

    assistant = _install_stub(monkeypatch, script)
    try:
        r = client.post("/v1/assistant", json={
            "message": "tình hình sao rồi", "tick": 22, "vehicle": "motorbike"})
        events, _ = _collect(r)
        queries = [d for e, d in events if e == "query"][0]["queries"]
        assert queries
        for q in queries:
            if "result" in q:
                assert q.get("evidence_class"), \
                    f"op {q['op']} surfaced values without a provenance label: {q}"
        # both newly-traced tools now appear
        assert {"get_street_state", "get_area_weather"} <= {q["op"] for q in queries}
    finally:
        assistant._client = None


@needs_scenario
def test_record_refuses_unlabelled_results():
    """The pairing is enforced in code, not by convention at each call site."""
    from app.routers import assistant
    stash: dict = {}
    with pytest.raises(ValueError, match="evidence_class"):
        assistant._record(stash, "get_street_state", result={"depth_p50_cm": 15.0})
    assert stash == {}, "a rejected record still mutated the trace"
