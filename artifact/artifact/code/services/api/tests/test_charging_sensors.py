"""Charging stations and sensor coverage: real locations, simulated reachability, and
an empty state that does not lie.

The charging feature was built after checking the data, and the data said something
inconvenient: OSM maps no station inside either demo bbox. These tests pin the honest
handling of that, because the tempting fix — a plausible pin — is exactly the failure the
rest of this codebase is built to prevent.
"""
import pytest
from conftest import needs_scenario, needs_feature

pytestmark = needs_scenario


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


# ---------- charging ----------

@needs_feature("charging")
def test_station_locations_are_real_and_reachability_is_simulated(client):
    """One payload, two provenance classes. Collapsing them would let a simulated verdict
    borrow the credibility of a real coordinate."""
    d = client.get("/v1/charging?at=24&vehicle=e_2w").json()
    assert d["location_evidence_class"] == "real geometry"
    assert d["access_evidence_class"] == "simulated"


@needs_feature("charging")
def test_every_station_comes_from_a_source_never_invented(client):
    import json
    import pathlib
    from app.deps import DATA
    raw = json.loads((pathlib.Path(DATA) / "raw" / "thuduc.charging.json").read_text())
    assert all(s["source"] == "osm" for s in raw["stations"])


@needs_feature("charging")
def test_empty_scene_is_reported_as_a_coverage_gap_not_as_absence(client):
    """No mapped station must never render as "there is nowhere to charge"."""
    d = client.get("/v1/charging?at=24&vehicle=e_2w").json()
    if d["n_in_scene"] == 0:
        assert d["no_station_mapped_in_scene"] is True
        assert d["coverage_note"], "an empty result with no caveat is a false claim"
        assert d["nearest_outside_scene"], "the nearest real station is still useful"


@needs_feature("charging")
def test_out_of_scene_stations_are_marked_unroutable(client):
    """The graph stops at the bbox, so a distance is honest but a route would not be."""
    d = client.get("/v1/charging?at=24&vehicle=e_2w").json()
    for s in d["nearest_outside_scene"]:
        assert s["routing_available"] is False
        assert s["why_no_routing"]
        assert s["km_from_scene_centre"] > 0 and s["bearing_from_scene_vi"]


@needs_feature("charging")
def test_charging_rejects_an_unknown_vehicle(client):
    assert client.get("/v1/charging?at=0&vehicle=hovercraft").status_code == 422


# ---------- sensor coverage ----------

def test_coverage_is_the_assimilation_footprint_not_a_viewshed(client):
    """Coverage means "edges this observation actually informs", which is checkable
    against the engine, unlike an invented camera cone."""
    d = client.get("/v1/ops/sensor-coverage").json()
    assert d["model"]["max_hops"] == 3
    assert d["model"]["hop_decay"][0] == 1.0
    assert "basin" in d["model"]["constraint"]
    assert d["note"]


def test_coverage_matches_the_engine_neighbourhood_exactly(client):
    """Not an approximation of the engine — the same function."""
    from app.engine import state
    sc = state.get("thuduc")
    d = client.get("/v1/ops/sensor-coverage?feed_id=camera-3").json()
    anchor = next(o["edge"] for o in sc.meta["feeds"] if o["feed_id"] == "camera-3")
    expected = sc.neighbourhood(anchor)
    served = {e["edge_id"]: e["weight"] for e in d["sensors"][0]["edges"]}
    assert len(served) == len(expected)
    for idx, w in expected.items():
        assert served[sc.g.edge_ids[idx]] == pytest.approx(w, abs=0.01)


def test_coverage_reports_the_gap_and_not_only_the_reach(client):
    """The useful number for this project is how little is observed, not how much."""
    d = client.get("/v1/ops/sensor-coverage").json()
    assert d["n_edges_covered"] < d["n_edges_total"]
    assert 0 < d["pct_length_covered"] < 100
    assert d["n_sensors"] > 0


def test_unknown_feed_is_404(client):
    assert client.get("/v1/ops/sensor-coverage?feed_id=camera-999").status_code == 404
