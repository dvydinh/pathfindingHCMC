"""Standing invariant gates (PLAN.md §0). These run at every milestone gate."""
import numpy as np
from hypothesis import given, strategies as st, settings
from app.engine.passability import risk_band, BAND_RANK, ENVELOPE, member_passability
from conftest import needs_scenario

finite = dict(allow_nan=False, allow_infinity=False)
pi_s = st.floats(0, 1, **finite)
w_s = st.floats(0, 100, **finite)
age_s = st.floats(0, 7200, **finite)

def rank(b: str) -> int:
    return BAND_RANK[b]

# ---- I2: uncertainty never renders as safety -------------------------------
@settings(max_examples=300)
@given(pi=pi_s, w1=w_s, w2=w_s, age=st.one_of(st.none(), age_s), src=st.booleans())
def test_I2_wider_interval_never_safer(pi, w1, w2, age, src):
    lo, hi = sorted([w1, w2])
    assert rank(risk_band(pi, lo, age, src, False)) <= rank(risk_band(pi, hi, age, src, False))

# ---- I3: staleness only raises risk ----------------------------------------
@settings(max_examples=300)
@given(pi=pi_s, w=w_s, a1=age_s, a2=age_s, src=st.booleans())
def test_I3_older_evidence_never_safer(pi, w, a1, a2, src):
    lo, hi = sorted([a1, a2])
    assert rank(risk_band(pi, w, lo, src, False)) <= rank(risk_band(pi, w, hi, src, False))

# ---- I4: official closure overrides everything -----------------------------
@settings(max_examples=200)
@given(pi=pi_s, w=w_s, age=st.one_of(st.none(), age_s), src=st.booleans())
def test_I4_closure_always_avoid(pi, w, age, src):
    assert risk_band(pi, w, age, src, True) == "avoid"

# ---- lower pi never safer ---------------------------------------------------
@settings(max_examples=300)
@given(p1=pi_s, p2=pi_s, w=w_s, age=st.one_of(st.none(), age_s), src=st.booleans())
def test_lower_pi_never_safer(p1, p2, w, age, src):
    lo, hi = sorted([p1, p2])
    assert rank(risk_band(hi, w, age, src, False)) <= rank(risk_band(lo, w, age, src, False))

# ---- envelope: deeper water never more passable ----------------------------
def test_envelope_monotone_depth():
    h = np.linspace(0, 80, 200)
    for v in ENVELOPE:
        p = member_passability(h, v)
        assert np.all(np.diff(p) <= 1e-12)

# ---- stricter vehicles are never more permissive at any depth --------------
def test_vehicle_ordering():
    h = np.linspace(0, 80, 200)
    assert np.all(member_passability(h, "e_2w") <= member_passability(h, "motorbike") + 1e-9)
    assert np.all(member_passability(h, "motorbike") <= member_passability(h, "response") + 1e-9)

# ---- I1/I6 on the live scenario --------------------------------------------
@needs_scenario
def test_I1_I6_state_tagged():
    from app.engine import state, passability
    sc = state.get("thuduc")
    out = passability.edge_states(sc, 10, "motorbike")
    assert out["evidence_class"] == "simulated"
    assert out["is_synthetic"] is True
    assert len(out["bands"]) == sc.E

@needs_scenario
def test_I4_closure_forces_pi_zero():
    from app.engine import state, passability
    sc = state.get("thuduc")
    e = int(np.argsort(-sc.g.sink)[500])
    sc.closures.add(e); sc.bump()
    try:
        out = passability.edge_states(sc, 20, "motorbike")
        assert out["pi"][e] == 0.0
        assert out["bands"][e] == passability.BAND_RANK["avoid"]
        assert "OFFICIAL_CLOSURE" in passability.edge_reasons(sc, 20, "motorbike", e)
    finally:
        sc.closures.discard(e); sc.bump()

@needs_scenario
def test_band_arrays_match_scalar():
    """The vectorised banding must mirror the property-tested scalar function."""
    import numpy as np
    from app.engine import state
    from app.engine.passability import band_arrays, risk_band, BAND_RANK
    sc = state.get("thuduc")
    bands, pi, p50, width, age_s, has_src, closed = band_arrays(sc, 18, "motorbike")
    rng = np.random.default_rng(0)
    for e in rng.integers(0, sc.E, 400):
        b = risk_band(float(pi[e]), float(width[e]),
                      float(age_s[e]) if has_src[e] else None,
                      bool(has_src[e]), bool(closed[e]))
        assert BAND_RANK[b] == bands[e], f"edge {e}"
