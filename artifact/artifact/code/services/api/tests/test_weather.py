"""Weather endpoint: forcing interpolation, local stats, provenance tags."""
import pytest
from conftest import needs_scenario

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

@needs_scenario
def test_weather_forcing_and_tags(client):
    r = client.get("/v1/weather", params={"at": 18})
    assert r.status_code == 200
    d = r.json()
    assert d["is_synthetic"] is True and d["evidence_class"] == "simulated"
    assert d["rain_mm_h"]["now"] > 0            # tick 18 is inside the rain event
    assert len(d["rain_curve"]) == 49

@needs_scenario
def test_weather_local_stats(client):
    r = client.get("/v1/weather", params={"at": 22, "bbox": "106.75,10.83,106.78,10.85"})
    d = r.json()
    assert "local" in d and d["local"]["n_edges"] > 0
    assert d["local"]["max_depth_cm"] >= d["local"]["mean_depth_cm"]

@needs_scenario
def test_weather_validation(client):
    assert client.get("/v1/weather", params={"at": 9999}).status_code == 422
    assert client.get("/v1/weather", params={"at": 5, "bbox": "garbage"}).status_code == 422


def test_rain_accumulation_is_reported_not_only_intensity(client):
    """Flood depth follows the integral of rainfall, not the instantaneous rate, so an
    intensity-only panel omits the number that actually explains the water."""
    d = client.get("/v1/weather?at=24").json()
    assert d["rain_accum_mm"] > 0
    assert d["rain_accum_total_mm"] >= d["rain_accum_mm"]
    assert len(d["rain_accum_curve_mm"]) == len(d["rain_curve"])
    assert d["units"]["rain_accum_mm"].startswith("mm")


def test_accumulation_is_monotone_over_the_event(client):
    """Rain cannot un-fall; a decreasing accumulation would mean the integral is wrong."""
    curve = client.get("/v1/weather?at=0").json()["rain_accum_curve_mm"]
    assert all(b >= a for a, b in zip(curve, curve[1:]))
    assert curve[0] == 0.0


def test_accumulation_matches_the_intensity_curve(client):
    """The accumulation must be the integral of the curve shown beside it, not a
    separately-derived number that could drift from it."""
    d = client.get("/v1/weather?at=0").json()
    rain, accum = d["rain_curve"], d["rain_accum_curve_mm"]
    expected = 0.0
    for i, r in enumerate(rain):
        expected += r * (5 / 60)          # 5-minute ticks
        assert abs(accum[i] - expected) < 0.15, f"drift at tick {i}"
