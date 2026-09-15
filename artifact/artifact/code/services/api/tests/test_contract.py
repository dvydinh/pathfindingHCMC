"""Contract drift guard (DECISIONS 002): responses must carry the EdgeState
required fields from packages/contracts/openapi.yaml."""
from conftest import needs_scenario

REQUIRED = ["edge_id", "edge_version", "depth_q", "pi", "risk_band", "evidence_class",
            "evidence_age_s", "source_mix", "reason_codes", "is_synthetic"]

@needs_scenario
def test_edge_state_contract():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/v1/state", params={"at": 10, "vehicle": "motorbike"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_synthetic"] is True and body["evidence_class"] == "simulated"
    r2 = c.get("/v1/passability", params={"at": 10, "vehicle": "motorbike"})
    assert r2.status_code == 200
    for e in r2.json()["edges"][:5]:
        for k in REQUIRED:
            assert k in e, f"missing {k}"

def test_invalid_tick_422():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/v1/state", params={"at": 99999, "vehicle": "motorbike"}).status_code == 422
    assert c.get("/v1/state", params={"at": 1, "vehicle": "tank"}).status_code == 422
