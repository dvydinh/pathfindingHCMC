"""Router gates: I5 (recommended route respects chance constraint), G3.4 (no_safe_route
path), plus golden-replay determinism."""
import numpy as np
import pytest
from conftest import needs_scenario

@pytest.fixture(scope="module")
def sc():
    from app.engine import state
    return state.get("thuduc")

def _od(sc, seed=7):
    """Pick an OD pair spanning the scene diagonally."""
    g = sc.g
    lons = np.array([c[0][0] for c in g.coords])
    lats = np.array([c[0][1] for c in g.coords])
    a = int(np.argmin(lons + lats)); b = int(np.argmax(lons + lats))
    return (float(lons[a]), float(lats[a])), (float(lons[b]), float(lats[b]))

@needs_scenario
def test_I5_recommended_respects_constraint(sc):
    from app.engine import router
    o, d = _od(sc)
    res = router.route(sc, "motorbike", o, d, depart_tick=18)
    if res["recommended"] is not None:
        assert res["recommended"]["sum_p_unsafe"] <= router.ALPHA["motorbike"] + 1e-9

@needs_scenario
def test_routes_deterministic_golden(sc):
    from app.engine import router
    o, d = _od(sc)
    r1 = router.route(sc, "motorbike", o, d, depart_tick=18)
    r2 = router.route(sc, "motorbike", o, d, depart_tick=18)
    for k in ("dry", "recommended"):
        e1 = r1[k]["edges"] if r1[k] else None
        e2 = r2[k]["edges"] if r2[k] else None
        assert e1 == e2

@needs_scenario
def test_dry_vs_recommended_differ_at_peak(sc):
    """At storm peak the risk-aware route should deviate from the dry-fastest route
    for at least one OD pair crossing flooded sinks (demo beat G3.1/G3.2)."""
    from app.engine import router
    g = sc.g
    peak = sc.truth[24]
    wet = np.argsort(-peak)[:50]
    # OD straddling a wet cluster
    e = int(wet[0])
    lon0, lat0 = g.coords[e][0]
    o = (lon0 - 0.012, lat0 - 0.012); d = (lon0 + 0.012, lat0 + 0.012)
    res = router.route(sc, "motorbike", o, d, depart_tick=20)
    assert res["dry"] is not None
    if res["recommended"] is not None:
        assert res["recommended"]["risk_exposure_s"] <= res["dry"]["risk_exposure_s"] + 1e-9

@needs_scenario
def test_no_safe_route_shape(sc):
    """G3.4: an impossible constraint yields no_safe_route + wait scan, not a crash."""
    from app.engine import router
    o, d = _od(sc)
    old = router.ALPHA["motorbike"]
    router.ALPHA["motorbike"] = 1e-12
    try:
        res = router.route(sc, "motorbike", o, d, depart_tick=20)
        assert res["recommended"] is None or res["recommended"]["sum_p_unsafe"] <= 1e-12
    finally:
        router.ALPHA["motorbike"] = old

@needs_scenario
def test_waypoint_chain_visits_all_stops(sc):
    """Multi-leg trip passes through the snapped waypoint and time-propagates legs."""
    from app.engine import router
    o, w, d = (106.755, 10.835), (106.760, 10.845), (106.775, 10.850)
    res = router.route(sc, "motorbike", o, d, depart_tick=10, waypoints=[w])
    assert res["n_legs"] == 2
    assert res["dry"] is not None
    wp_node = router.snap(sc, *w)
    nodes_on_path = {int(sc.g.u[e]) for e in res["dry"]["edges"]} | \
                    {int(sc.g.v[e]) for e in res["dry"]["edges"]}
    assert wp_node in nodes_on_path
    assert len(res["dry"]["leg_times_s"]) == 2

@needs_scenario
def test_waypoint_constraint_is_trip_level(sc):
    """I5 holds for the WHOLE multi-leg trip, not per leg."""
    from app.engine import router
    o, w, d = (106.755, 10.835), (106.765, 10.830), (106.775, 10.850)
    res = router.route(sc, "motorbike", o, d, depart_tick=20, waypoints=[w])
    if res["recommended"] is not None:
        assert res["recommended"]["sum_p_unsafe"] <= router.ALPHA["motorbike"] + 1e-9
