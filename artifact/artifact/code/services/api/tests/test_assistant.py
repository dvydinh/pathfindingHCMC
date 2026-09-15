"""F1 assistant: availability gating and read-only tool construction."""
import pytest
from conftest import needs_scenario

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

def _reset(monkeypatch, key: str | None):
    from app.routers import assistant
    assistant._client = None
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)

def test_unavailable_without_key(client, monkeypatch):
    from app.routers import assistant
    _reset(monkeypatch, None)
    assert client.get("/v1/assistant/status").json()["available"] is False
    r = client.post("/v1/assistant", json={"message": "hi", "tick": 0,
                                           "vehicle": "motorbike"})
    assert r.status_code == 503
    assistant._client = None   # leave clean

def test_input_caps(client, monkeypatch):
    _reset(monkeypatch, "sk-test-not-real")
    r = client.post("/v1/assistant", json={"message": "x" * 3000, "tick": 0,
                                           "vehicle": "motorbike"})
    assert r.status_code == 422           # message over cap rejected by schema
    from app.routers import assistant
    assistant._client = None

def _tool_map(scene="thuduc", stash=None):
    from app.routers import assistant
    tools = assistant._make_tools(scene, stash if stash is not None else {})
    out = {}
    for t in tools:
        schema = t.to_dict() if hasattr(t, "to_dict") else dict(t)
        out[schema.get("name") or getattr(t, "name", None)] = t
    return out

@needs_scenario
def test_tools_are_readonly_and_complete(monkeypatch):
    """The tool set exposes exactly the read-only lookups — no write paths."""
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    assert set(_tool_map()) == {"find_place", "plan_route", "plan_trip",
                                "find_departure_window", "get_street_state",
                                "get_area_summary", "get_area_weather", "get_edge_state"}
    assistant._client = None

@needs_scenario
def test_no_tool_accepts_coordinates(monkeypatch):
    """Coordinate authorship is removed from the model, not merely discouraged: if no
    tool takes lon/lat, an invented coordinate has nowhere to enter the system."""
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    for name, t in _tool_map().items():
        schema = t.to_dict() if hasattr(t, "to_dict") else dict(t)
        params = set((schema.get("input_schema") or {}).get("properties", {}))
        assert not (params & {"lon", "lat", "o_lon", "o_lat", "d_lon", "d_lat"}), \
            f"{name} accepts coordinates from the model"
    assistant._client = None

@needs_scenario
def test_plan_route_refuses_a_place_outside_the_scene(monkeypatch):
    """The whole point: an out-of-area name must not become a confident local route."""
    import json
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    stash: dict = {}
    plan = _tool_map(stash=stash)["plan_route"]
    out = json.loads(plan.call({"origin": "chợ Bến Thành", "destination": "chợ Thủ Đức",
                                "depart_tick": 12, "vehicle": "motorbike"}))
    assert out["status"] == "not_found" and out["field"] == "origin"
    assert "route" not in stash, "a rejected query still ran the router"
    assistant._client = None

@needs_scenario
def test_plan_trip_rejects_the_whole_trip_when_one_stop_fails(monkeypatch):
    """Partial resolution would invite the model to fill the gap from its own knowledge,
    which is the channel this design removes. So the trip fails whole."""
    import json
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    stash: dict = {}
    out = json.loads(_tool_map(stash=stash)["plan_trip"].call(
        {"stops": ["chợ Thủ Đức", "chợ Bến Thành", "ga Bình Thái"],
         "depart_tick": 24, "vehicle": "motorbike"}))
    assert out["status"] == "not_found" and out["stop_index"] == 1
    assert "route" not in stash, "a rejected trip still ran the router"
    assistant._client = None

@needs_scenario
def test_plan_trip_compares_variants_in_one_call(monkeypatch):
    """The point of the lower tier: N routings, one model round-trip, no model arithmetic."""
    import json
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    stash: dict = {}
    out = json.loads(_tool_map(stash=stash)["plan_trip"].call(
        {"stops": ["chợ Thủ Đức", "đại học Nông Lâm"], "depart_tick": 24,
         "vehicle": "motorbike", "compare_departures": [30, 36],
         "compare_vehicles": ["car"]}))
    assert out["plan"]["n_legs"] == 1
    assert len(out["comparisons"]) == 3
    assert out["comparison_note"]
    trace = [q for q in stash["trace"] if q["op"] == "plan_trip"]
    assert trace and trace[0]["n_comparisons"] == 3
    assistant._client = None

@needs_scenario
def test_plan_trip_routes_through_every_waypoint(monkeypatch):
    import json
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    out = json.loads(_tool_map()["plan_trip"].call(
        {"stops": ["chợ Thủ Đức", "đại học Nông Lâm", "ga Bình Thái"],
         "depart_tick": 24, "vehicle": "motorbike"}))
    assert len(out["stops"]) == 3 and out["plan"]["n_legs"] == 2
    assistant._client = None

@needs_scenario
def test_plan_trip_never_recommends_a_non_compliant_variant(monkeypatch):
    """A faster option that fails the chance constraint is not an option."""
    import json
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    out = json.loads(_tool_map()["plan_trip"].call(
        {"stops": ["chợ Thủ Đức", "đại học Nông Lâm"], "depart_tick": 24,
         "vehicle": "motorbike", "compare_departures": [30, 36]}))
    best = out.get("lowest_exposure_option")
    if best is not None:
        chosen = [v for v in [out["plan"]] + out["comparisons"]
                  if v["depart_tick"] == best["depart_tick"]
                  and v["vehicle"] == best["vehicle"]]
        assert chosen and chosen[0]["status"] == "ok"
    assistant._client = None

@needs_scenario
def test_similar_names_are_labelled_as_not_the_asked_place(monkeypatch):
    """Found by live probing: the model offered near-miss names as substitutes for a
    market in another district. They must be labelled as what they are."""
    import json
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    out = json.loads(_tool_map()["find_place"].call({"query": "chợ Bến Thành"}))
    assert out["status"] == "not_found"
    assert "did_you_mean" not in out, "the bare key invited use as an alternative"
    assert out["names_that_look_similar"]
    assert "KHÔNG PHẢI" in out["warning_about_similar_names"]
    assistant._client = None

@needs_scenario
def test_no_safe_route_forbids_quoting_the_dry_route_as_an_option(monkeypatch):
    """Found by live probing: with no compliant route the model quoted the dry route's
    travel time, which reads as 'you can do it in 16 minutes'."""
    import json
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    tools = _tool_map()
    for name, args in (("plan_route", {"origin": "chợ Thủ Đức",
                                       "destination": "đại học Nông Lâm",
                                       "depart_tick": 24, "vehicle": "motorbike"}),
                       ("plan_trip", {"stops": ["chợ Thủ Đức", "đại học Nông Lâm"],
                                      "depart_tick": 24, "vehicle": "motorbike"})):
        out = json.loads(tools[name].call(args))
        status = out.get("status") or out["plan"]["status"]
        if status == "no_safe_route":
            assert "fastest_dry" in json.dumps(out), "fixture no longer exercises the case"
            assert "không được nêu như một lựa chọn" in out["instruction"]
    assistant._client = None

@needs_scenario
def test_ambiguity_becomes_tappable_options(monkeypatch):
    """An ambiguous name is a real choice between real places, so offer it as a list."""
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    stash: dict = {}
    _tool_map(stash=stash)["find_place"].call({"query": "Linh Xuân"})
    pending = stash["choices"]["Linh Xuân"]
    assert len(pending["options"]) > 1
    assert all(o["name"] for o in pending["options"])
    assistant._client = None

@needs_scenario
def test_not_found_offers_no_tappable_near_miss(monkeypatch):
    """names_that_look_similar are explicitly NOT the place asked for. One tap must never
    be enough to route to a street that merely rhymes with another district's market."""
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    stash: dict = {}
    _tool_map(stash=stash)["find_place"].call({"query": "chợ Bến Thành"})
    assert stash["choices"]["chợ Bến Thành"]["options"] == []
    assistant._client = None

@needs_scenario
def test_resolving_a_name_clears_its_pending_choice(monkeypatch):
    """Otherwise a picker for an already-settled name would linger on screen."""
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    stash: dict = {}
    tools = _tool_map(stash=stash)
    tools["find_place"].call({"query": "Linh Xuân"})
    assert "Linh Xuân" in stash["choices"]
    tools["find_place"].call({"query": "Ủy ban nhân dân phường Linh Xuân"})
    tools["plan_route"].call({"origin": "chợ Thủ Đức",
                              "destination": "Ủy ban nhân dân phường Linh Xuân",
                              "depart_tick": 24, "vehicle": "motorbike"})
    assert "Ủy ban nhân dân phường Linh Xuân" not in stash.get("choices", {})
    assistant._client = None

@needs_scenario
def test_query_trace_records_rejections_for_audit(monkeypatch):
    """Guardrail 4: the formal query is logged whether it executed or was refused."""
    import json
    _reset(monkeypatch, "sk-test-not-real")
    from app.routers import assistant
    stash: dict = {}
    tools = _tool_map(stash=stash)
    tools["find_place"].call({"query": "Hồ Gươm"})
    json.loads(tools["plan_route"].call(
        {"origin": "Hồ Gươm", "destination": "chợ Thủ Đức",
         "depart_tick": 12, "vehicle": "motorbike"}))
    ops = [(q["op"], q["status"]) for q in stash["trace"]]
    assert ("find_place", "not_found") in ops
    assert ("plan_route", "not_found") in ops
    assistant._client = None
