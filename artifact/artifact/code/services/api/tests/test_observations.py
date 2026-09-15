"""M5 gates: G5.1 posterior narrows, G5.2 locality, G5.4 (I7) no raw image,
G5.5 malformed/spoofed rejection."""
import numpy as np
import pytest
from conftest import needs_scenario

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

@pytest.fixture()
def sc():
    from app.engine import state
    s = state.get("thuduc")
    saved = list(s.user_obs)
    yield s
    with s.lock:
        s.user_obs = saved
    s.bump()

@needs_scenario
def test_G51_report_narrows_local_posterior(sc, client):
    from app.engine import state
    e = int(np.argsort(-sc.g.sink)[3])
    edge_id = sc.g.edge_ids[e]
    tick = 22
    p10a, p50a, p90a = sc.quantiles(tick)
    before = float(p90a[e] - p10a[e])
    r = client.post("/v1/observations", json={
        "edge_id": edge_id, "tick": tick, "category": "footrest",
        "vehicle_context": "motorbike", "consent": True})
    assert r.status_code == 200
    assert r.json()["is_synthetic"] is True
    p10b, p50b, p90b = sc.quantiles(tick)
    after = float(p90b[e] - p10b[e])
    assert after <= before + 1e-6, f"width grew: {before} -> {after}"

@needs_scenario
def test_G52_update_is_local(sc, client):
    tick = 22
    e = int(np.argsort(-sc.g.sink)[5])
    near = set(sc.neighbourhood(e).keys())
    far = [i for i in range(0, sc.E, 997) if i not in near][:40]
    p50_before = sc.quantiles(tick)[1][far].copy()
    W_before = sc.weights(tick)[far].copy()
    client.post("/v1/observations", json={
        "edge_id": sc.g.edge_ids[e], "tick": tick, "category": "impassable",
        "vehicle_context": "none", "consent": True})
    W_after = sc.weights(tick)[far]
    assert np.allclose(W_before, W_after), "far edges' weights changed"

@needs_scenario
def test_G55_malformed_rejected(sc, client):
    edge_id = sc.g.edge_ids[10]
    assert client.post("/v1/observations", json={
        "edge_id": edge_id, "tick": 5, "category": "tsunami",
        "consent": True}).status_code == 422
    assert client.post("/v1/observations", json={
        "edge_id": edge_id, "tick": 5, "category": "ankle",
        "consent": False}).status_code == 422
    assert client.post("/v1/observations", json={
        "edge_id": "no-such-edge", "tick": 5, "category": "ankle",
        "consent": True}).status_code == 422
    # coordinate spoof: location ~2 km from the edge
    ex, ey = sc.g.coords[10][0]
    assert client.post("/v1/observations", json={
        "edge_id": edge_id, "tick": 5, "category": "ankle", "consent": True,
        "location": [ex + 0.02, ey + 0.02]}).status_code == 422

@needs_scenario
def test_G54_I7_no_raw_image_accepted(sc, client):
    """A large payload masquerading as a thumbnail must be rejected."""
    import base64
    edge_id = sc.g.edge_ids[10]
    big = base64.b64encode(b"x" * 20_000).decode()
    r = client.post("/v1/observations", json={
        "edge_id": edge_id, "tick": 5, "category": "ankle", "consent": True,
        "thumb_b64": big})
    assert r.status_code == 422
