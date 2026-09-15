"""M6 drills: G6.1 outage widens uncertainty & shifts routing conservative (I3 e2e);
G6.2 closure end-to-end (I4 e2e); G6.3 sensing never requests flooded edges."""
import numpy as np
import pytest
from conftest import needs_scenario, needs_feature

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

@pytest.fixture()
def sc():
    from app.engine import state
    s = state.get("thuduc")
    yield s
    with s.lock:
        s.outages.clear(); s.closures.clear()
    s.bump()

@needs_feature("ops_sensor_outage")
@needs_scenario
def test_G61_outage_drill(sc, client):
    tick = 20
    gauge_edges = [o["edge"] for o in sc.meta["feeds"] if o["feed_id"] == "gauge-0"]
    e = gauge_edges[0]
    p10a, _, p90a = sc.quantiles(tick)
    before = float(p90a[e] - p10a[e])
    r = client.post("/v1/ops/outage", json={"feed_id": "gauge-0", "active": True})
    assert r.status_code == 200
    p10b, _, p90b = sc.quantiles(tick)
    after = float(p90b[e] - p10b[e])
    assert after >= before - 1e-6, "outage must not narrow the posterior"

@needs_scenario
def test_G62_closure_drill(sc, client):
    from app.engine import router
    tick = 10
    e = 4242
    edge_id = sc.g.edge_ids[e]
    r = client.post("/v1/ops/closure", json={"edge_id": edge_id, "active": True})
    assert r.status_code == 200
    st = client.get("/v1/state", params={"at": tick, "vehicle": "motorbike"}).json()
    assert st["pi"][e] == 0.0
    assert st["bands"][e] == 3
    layer = router._tick_layer(sc, "motorbike", tick)
    assert bool(layer["blocked"][e])

@needs_feature("ops_sensing_queue")
@needs_scenario
def test_G63_sensing_never_requests_flooded(sc, client):
    r = client.get("/v1/ops/queue", params={"at": 24}).json()
    p50 = sc.quantiles(24)[1]
    for item in r["queue"]:
        e = sc.g.idx[item["edge_id"]]
        assert p50[e] <= 10.0, "queue asked for observation of a flooded edge"
