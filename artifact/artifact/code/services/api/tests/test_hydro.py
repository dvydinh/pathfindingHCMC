"""Physics guard tests (G2.3): no uphill flow by construction, depths finite/non-negative."""
import numpy as np
from conftest import needs_scenario

@needs_scenario
def test_truth_physical():
    from app.engine import state
    sc = state.get("thuduc")
    assert np.all(sc.truth >= 0)
    assert np.all(np.isfinite(sc.truth))
    assert np.all(sc.ens >= 0)

@needs_scenario
def test_downhill_only():
    from app.engine import state
    sc = state.get("thuduc")
    g = sc.g
    for i in range(0, g.n, 500):
        for j in g.downhill[i]:
            if j is not None:
                assert g.z_min[j] <= g.z_min[i] + 0.05 + 1e-9

@needs_scenario
def test_band_change_count():
    """G2.2: >=500 edges change band across the event."""
    from app.engine import state, passability
    sc = state.get("thuduc")
    b0 = np.array(passability.edge_states(sc, 0, "motorbike")["bands"])
    b1 = np.array(passability.edge_states(sc, 20, "motorbike")["bands"])
    assert (b0 != b1).sum() >= 500
