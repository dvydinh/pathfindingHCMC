"""Departure-window search: when does this trip actually clear?

route() probes only two wait offsets to protect the interactive p95, so a null
wait_suggestion there can hide a compliant departure 15 minutes away. These tests pin the
thorough search that answers the question properly, and pin the honesty of both: a partial
search must announce that it is partial.
"""
import pytest
from conftest import needs_scenario

pytestmark = needs_scenario


@pytest.fixture(scope="module")
def sc():
    from app.engine import state
    return state.get("thuduc")


@pytest.fixture(scope="module")
def od():
    from app.engine import gazetteer as gz
    o = gz.resolve("thuduc", "chợ Thủ Đức")["candidates"][0]
    d = gz.resolve("thuduc", "đại học Nông Lâm")["candidates"][0]
    return (o["lon"], o["lat"]), (d["lon"], d["lat"])


def test_finds_a_compliant_departure_when_one_exists(sc, od, ):
    from app.engine import router
    w = router.departure_window(sc, "motorbike", od[0], od[1], 0)
    assert w["found"] is True
    assert w["earliest_compliant"]["depart_tick"] == 0
    assert w["earliest_compliant"]["travel_min"] > 0


def test_reports_not_found_without_implying_it_never_clears(sc, od):
    """The scenario floods and does not recede, so this window genuinely has no answer.
    The payload must say what it searched rather than assert impossibility."""
    from app.engine import router
    w = router.departure_window(sc, "motorbike", od[0], od[1], 24)
    assert w["found"] is False
    assert w["earliest_compliant"] is None
    assert w["window_minutes"] > 0 and w["step_minutes"] > 0
    assert w["probed_ticks"], "a search that reports nothing must show where it looked"


def test_scan_is_coarse_to_fine_not_brute_force(sc, od):
    """Cost discipline: a two-hour window must not cost one A* per tick."""
    from app.engine import router
    w = router.departure_window(sc, "motorbike", od[0], od[1], 24)
    span = w["searched_to_tick"] - w["from_tick"] + 1
    assert len(w["probed_ticks"]) < span, "scan degenerated into per-tick brute force"


def test_refinement_walks_back_to_the_true_earliest(sc, od, monkeypatch):
    """The coarse step can overshoot the real crossing by up to two ticks. Simulated with
    a known transition so the branch is exercised deterministically."""
    from app.engine import router
    fake = {"travel_time_s": 600.0, "risk_exposure_s": 1.0, "sum_p_unsafe": 0.0,
            "edges": [], "max_edge_risk": 0.0}

    def compliant(sc_, vehicle, nodes, tick):
        return (fake, True) if tick >= 26 else (None, False)

    monkeypatch.setattr(router, "_compliant", compliant)
    w = router.departure_window(sc, "motorbike", od[0], od[1], 24)
    assert w["found"] is True
    # coarse probes land on 24 and 27; the true crossing at 26 is only reachable by
    # walking back from 27.
    assert w["earliest_compliant"]["depart_tick"] == 26


def test_route_declares_its_wait_search_is_partial(sc, od):
    """A null wait must not read as "waiting never helps"."""
    from app.engine import router
    res = router.route(sc, "motorbike", od[0], od[1], 24)
    assert res["wait_search_is_partial"] is True
    assert res["wait_probed_offsets_min"] == [30, 60]


@needs_scenario
def test_assistant_exposes_the_window_tool_and_the_rain_curve(monkeypatch):
    import json
    from test_assistant import _tool_map, _reset
    _reset(monkeypatch, "sk-test-not-real")
    tools = _tool_map()
    assert "find_departure_window" in tools

    wx = json.loads(tools["get_area_weather"].call({"tick": 12}))
    assert wx["rain_curve_mm_h"], "the model cannot reason about a curve it never sees"
    assert isinstance(wx["peak_tick"], int)
    assert "eases_off_tick" in wx

    out = json.loads(tools["find_departure_window"].call(
        {"origin": "chợ Thủ Đức", "destination": "đại học Nông Lâm",
         "vehicle": "motorbike", "from_tick": 24, "within_minutes": 60}))
    assert out["found"] is False
    assert "KHONG duoc suy ra" in out["instruction"]

    from app.routers import assistant
    assistant._client = None


@needs_scenario
def test_window_tool_refuses_an_out_of_area_place(monkeypatch):
    import json
    from test_assistant import _tool_map, _reset
    _reset(monkeypatch, "sk-test-not-real")
    out = json.loads(_tool_map()["find_departure_window"].call(
        {"origin": "chợ Bến Thành", "destination": "chợ Thủ Đức",
         "vehicle": "motorbike", "from_tick": 0}))
    assert out["status"] == "not_found"
    from app.routers import assistant
    assistant._client = None
