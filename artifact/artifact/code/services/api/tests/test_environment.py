"""Ambient layer: real data, real clock, and honest about its own resolution.

This layer differs from every other one in the demo by being *measured* rather than
simulated, so the tests are mostly about keeping that distinction from eroding — and
about not letting a coarse source be rendered as if it were fine-grained.
"""
import pytest
from conftest import needs_feature


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@needs_feature("environment")
def test_layer_is_labelled_observed_not_simulated(client):
    """The flood layer is a synthetic storm; this one is not. Mislabelling either way
    would break the provenance contract the whole demo rests on (I1/I6)."""
    d = client.get("/v1/environment?hour=0").json()
    assert d["evidence_class"] == "observed"
    assert d["is_synthetic"] is False


@needs_feature("environment")
def test_layer_declares_it_does_not_touch_routing(client):
    """Heat and dust change what a trip costs a rider, but the safety case is about
    water. Widening it silently would be a change to the safety argument."""
    d = client.get("/v1/environment?hour=0").json()
    assert d["affects_routing"] is False
    assert d["independent_of_scenario_clock"] is True


def test_engine_never_imports_the_ambient_layer():
    """Enforced structurally, not by promise: no passability or routing module may read
    ambient conditions."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "engine"
    for name in ("passability.py", "router.py", "hydro.py", "state.py"):
        src = (root / name).read_text()
        assert "environment" not in src, f"{name} reached into the ambient layer"


@needs_feature("environment")
def test_tiles_carry_no_more_detail_than_the_source(client):
    """A dozen tiles per axis is a rendering convenience; the number of *distinct* values
    must still equal the number of real source cells, so no structure is invented."""
    d = client.get("/v1/environment?hour=6").json()
    assert d["tile_assignment"] == "nearest_source_cell"
    assert len({t["cell"] for t in d["tiles"]}) <= d["n_source_cells"]
    assert d["n_source_cells"] >= 1
    assert d["source_cell_span_km"] > 0


@needs_feature("environment")
def test_every_served_metric_has_a_unit(client):
    """A bare number for PM2.5 or apparent temperature is not interpretable."""
    d = client.get("/v1/environment?hour=0").json()
    for m in d["metrics"]:
        assert m in d["units"]
    for cell in d["cells"]:
        for m in d["metrics"]:
            assert m in cell


@needs_feature("environment")
def test_hour_is_clamped_not_rejected(client):
    """The series is finite; a slider past its end should pin, not 500."""
    last = client.get("/v1/environment?hour=0").json()["n_hours"] - 1
    assert client.get("/v1/environment?hour=99999").json()["hour_index"] == last
    assert client.get("/v1/environment?hour=-5").json()["hour_index"] == 0


@needs_feature("environment")
def test_series_endpoint_reports_what_it_averaged_over(client):
    d = client.get("/v1/environment/series?metric=apparent_temperature").json()
    assert d["unit"] == "°C"
    assert len(d["values"]) == len(d["time"])
    assert d["averaged_over_source_cells"] >= 1


@needs_feature("environment")
def test_unknown_metric_is_rejected(client):
    assert client.get("/v1/environment/series?metric=vibes").status_code == 422


@needs_feature("environment")
def test_provenance_names_the_source_and_licence(client):
    d = client.get("/v1/environment?hour=0").json()
    assert "Open-Meteo" in d["source"]["weather"]
    assert "Open-Meteo" in d["source"]["air_quality"]
    assert d["source"]["licence"]
    assert d["fetched_at"], "a real snapshot without a fetch time cannot be aged"
