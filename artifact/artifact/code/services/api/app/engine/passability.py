"""Vehicle-specific conservative passability (proposal C4) + risk banding.

Envelope table: conservative still-water thresholds (cm), hand-authored from public
manufacturer/agency guidance with safety margins — never learned from risky attempts.
Documented with sources in docs/MODEL_CARD.md.
"""
from __future__ import annotations
import numpy as np
from .state import Scenario, STALE_S, _sig

# vehicle -> (caution_cm, refuse_cm)
ENVELOPE = {
    "motorbike": (10.0, 20.0),
    "e_2w": (8.0, 15.0),
    "car": (15.0, 25.0),
    "response": (25.0, 40.0),
}
SIGMOID_SCALE = 2.5     # cm; smoothness of the conservative envelope
BAND_RANK = {"low": 0, "unknown": 1, "uncertain": 2, "avoid": 3}

def member_passability(h_cm: np.ndarray, vehicle: str) -> np.ndarray:
    """P(passable | depth) per member — smooth conservative step at the refuse line."""
    _, refuse = ENVELOPE[vehicle]
    return _sig((refuse - h_cm) / SIGMOID_SCALE)

def pi_matrix(sc: Scenario, vehicle: str, tick: int) -> np.ndarray:
    """Posterior passability per edge at one tick (weights-marginalised)."""
    key = (vehicle, tick, sc.version)
    if key in sc._pi_cache:
        return sc._pi_cache[key]
    W = sc.weights(tick)
    p = (member_passability(sc.ens[tick].astype(np.float64), vehicle) * W).sum(axis=1)
    p = np.where(sc.g.access[vehicle], p, 0.0)
    sc._pi_cache[key] = p
    return p

def risk_band(pi: float, width_cm: float, age_s: float | None,
              has_sources: bool, closed: bool) -> str:
    """Pure banding function. Property-tested invariants:
    I2 — wider interval can only increase caution rank;
    I3 — larger age can only increase caution rank;
    I4 — closed dominates everything."""
    if closed:
        return "avoid"
    if pi < 0.55:
        return "avoid"
    if pi < 0.85 or width_cm > 15.0 or (age_s is not None and age_s > STALE_S):
        return "uncertain"
    if not has_sources and width_cm > 6.0:
        return "unknown"
    return "low"

def reason_codes(pi: float, width_cm: float, age_s: float | None, has_sources: bool,
                 closed: bool, outage_hit: bool, conflict: bool, rising: bool) -> list[str]:
    out = []
    if closed: out.append("OFFICIAL_CLOSURE")
    if pi < 0.55: out.append("DEPTH_ABOVE_ENVELOPE")
    if outage_hit: out.append("SENSOR_OUTAGE")
    if conflict: out.append("SOURCE_CONFLICT")
    if has_sources and age_s is not None and age_s > STALE_S: out.append("GAUGE_STALE")
    if not has_sources: out.append("NO_COVERAGE")
    if rising: out.append("RISING_TREND")
    return out or ["OK"]

def band_arrays(sc: Scenario, tick: int, vehicle: str):
    """Vectorised banding. Mirrors risk_band() exactly — asserted by tests."""
    p10, p50, p90 = sc.quantiles(tick)
    pi = pi_matrix(sc, vehicle, tick).copy()
    last = sc.last_obs_tick(tick)
    has_src = last >= 0
    age_s = np.where(has_src, (tick - last) * sc.tick_s, -1).astype(np.int64)
    width = p90 - p10
    closed = np.zeros(sc.E, dtype=bool)
    if sc.closures:
        closed[list(sc.closures)] = True
    bands = np.zeros(sc.E, dtype=np.int8)                       # low
    unknown = (~has_src) & (width > 6.0)
    bands[unknown] = BAND_RANK["unknown"]
    uncertain = (pi < 0.85) | (width > 15.0) | (has_src & (age_s > STALE_S))
    bands[uncertain] = BAND_RANK["uncertain"]
    avoid = (pi < 0.55) | closed
    bands[avoid] = BAND_RANK["avoid"]
    pi[closed] = 0.0            # I4: closure forces pi to 0 AFTER inference
    return bands, pi, p50, width, age_s, has_src, closed

def edge_states(sc: Scenario, tick: int, vehicle: str) -> dict:
    """Compact aligned-array state for the whole scene (client joins by index).
    Cached per (tick, vehicle, version)."""
    key = ("states", vehicle, tick, sc.version)
    if key in sc._pi_cache:
        return sc._pi_cache[key]
    while len(sc._pi_cache) > 900:
        del sc._pi_cache[next(iter(sc._pi_cache))]
    bands, pi, p50, width, age_s, has_src, closed = band_arrays(sc, tick, vehicle)
    out = {
        "model_version": f"demo-{sc.meta['spec_hash']}",
        "tick": tick, "vehicle": vehicle,
        "bands": bands.tolist(),
        "pi": np.round(pi, 3).tolist(),
        "p50_cm": np.round(p50, 1).tolist(),
        "width_cm": np.round(width, 1).tolist(),
        "age_s": age_s.tolist(),
        "evidence_class": "simulated",     # I1/I6: every state in this demo is simulated
        "is_synthetic": True,
    }
    sc._pi_cache[key] = out
    return out

def edge_reasons(sc: Scenario, tick: int, vehicle: str, e: int) -> list[str]:
    """Reason codes for one edge (inspector / route explanation)."""
    bands, pi, p50, width, age_s, has_src, closed = band_arrays(sc, tick, vehicle)
    prev = max(tick - 2, 0)
    _, p50_prev, _ = sc.quantiles(prev)
    rising = bool((p50[e] - p50_prev[e]) > 3.0) if prev != tick else False
    conflicts = sc.conflict_edges(tick)
    outaged = _outage_hit(sc, tick)
    return reason_codes(float(pi[e]), float(width[e]),
                        float(age_s[e]) if has_src[e] else None, bool(has_src[e]),
                        bool(closed[e]), e in outaged, e in conflicts, rising)

def _outage_hit(sc: Scenario, tick: int) -> set[int]:
    hit: set[int] = set()
    if not sc.outages:
        return hit
    for o in sc.meta["feeds"]:
        if o["feed_id"] in sc.outages:
            hit |= set(sc.neighbourhood(o["edge"]).keys())
    return hit
