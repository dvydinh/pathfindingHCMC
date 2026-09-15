"""Active sensing (proposal C6): rank unobserved edges by
EIG x Impact x Reachability / (Cost + SafetyRisk). Decision-weighted: EIG counts
how much this edge's state matters to *recent routing queries*, and the system
never requests observation of an edge currently estimated flooded."""
from __future__ import annotations
import numpy as np
from .state import Scenario
from .passability import pi_matrix

def queue(sc: Scenario, tick: int, vehicle: str = "motorbike", k: int = 12) -> list[dict]:
    p10, p50, p90 = sc.quantiles(tick)
    width = p90 - p10
    eig = width / max(width.max(), 1e-6)                       # posterior spread
    last = sc.last_obs_tick(tick)
    unobserved = last < 0
    # decision weight: how often did recent route searches touch this edge
    touch = np.zeros(sc.E)
    for edges in sc.recent_routes:
        for e in edges:
            touch[e] += 1.0
    impact = 0.3 + touch / max(touch.max(), 1.0) + 0.4 * sc.g.sink
    reach = np.where(sc.g.access["motorbike"], 1.0, 0.4)
    pi = pi_matrix(sc, vehicle, tick)
    safety_risk = np.clip(1.2 - pi, 0.05, None) * 4.0          # flooded edges: huge cost
    flooded_now = p50 > 10.0
    score = np.where(unobserved & ~flooded_now,
                     eig * impact * reach / (1.0 + safety_risk), 0.0)
    top = np.argsort(-score)[:k]
    return [{
        "edge_id": sc.g.edge_ids[int(e)],
        "score": round(float(score[e]), 4),
        "expected_info": round(float(eig[e]), 3),
        "decision_touches": int(touch[e]),
        "est_p50_cm": round(float(p50[e]), 1),
        "safe_to_observe": bool(~flooded_now[e]),
        "ask": "categorical report from a safe vantage point",
    } for e in top if score[e] > 0]
