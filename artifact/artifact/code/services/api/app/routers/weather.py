"""Area weather panel (simulated): scenario rain/tide forcing at and after a tick,
plus local flood statistics for the requested viewport. Everything is tagged
simulated — the demo has no live meteorology feed (see DATA_REGISTER)."""
import numpy as np
from fastapi import APIRouter, HTTPException
from ..deps import default_scene
from ..engine import state
from ..sim.storm import spec_for

api = APIRouter(prefix="/v1")

def _curve(points: list, t: float) -> float:
    xs, ys = zip(*points)
    return float(np.interp(t, xs, ys))

@api.get("/weather")
def weather(at: int, bbox: str | None = None, scene: str | None = None) -> dict:
    s = scene or default_scene()
    sc = state.get(s)
    if not 0 <= at < sc.T:
        raise HTTPException(422, f"tick out of range 0..{sc.T - 1}")
    spec, _ = spec_for(s)
    per_tick = 15 // spec["tick_minutes"]          # ticks per 15 minutes
    def rain(t): return round(_curve(spec["rain_mm_h"], min(t, sc.T - 1)), 1)
    def tide(t): return round(_curve(spec["tide_m"], min(t, sc.T - 1)), 2)

    out = {
        "tick": at,
        "rain_mm_h": {"now": rain(at), "in_15m": rain(at + per_tick),
                      "in_30m": rain(at + 2 * per_tick), "in_60m": rain(at + 4 * per_tick)},
        "tide_m": {"now": tide(at), "in_60m": tide(at + 4 * per_tick)},
        "rain_curve": [rain(t) for t in range(sc.T)],     # sparkline over the event
        "evidence_class": "simulated", "is_synthetic": True,
    }
    # Intensity alone does not say how much water has arrived, and depth is driven by the
    # integral, not the instantaneous rate. Accumulate the curve at tick resolution.
    hours_per_tick = spec["tick_minutes"] / 60.0
    accum, running = [], 0.0
    for t in range(sc.T):
        running += rain(t) * hours_per_tick
        accum.append(round(running, 1))
    out["rain_accum_mm"] = accum[at]
    out["rain_accum_total_mm"] = accum[-1]
    out["rain_accum_curve_mm"] = accum
    out["rain_accum_next_60m_mm"] = round(
        sum(rain(min(at + i, sc.T - 1)) for i in range(1, 4 * per_tick + 1))
        * hours_per_tick, 1)
    out["units"] = {"rain_mm_h": "mm/hour (intensity)",
                    "rain_accum_mm": "mm fallen since the event started",
                    "tide_m": "metres"}
    if bbox:
        try:
            w, s_, e, n = (float(x) for x in bbox.split(","))
        except ValueError:
            raise HTTPException(422, "bbox must be w,s,e,n")
        key = "edge_lonlat"
        if key not in sc._pi_cache:
            g = sc.g
            sc._pi_cache[key] = (np.array([c[0][0] for c in g.coords]),
                                 np.array([c[0][1] for c in g.coords]))
        lon, lat = sc._pi_cache[key]
        mask = (lon >= w) & (lon <= e) & (lat >= s_) & (lat <= n)
        if mask.any():
            p10, p50, p90 = sc.quantiles(at)
            prev = max(at - 2, 0)
            _, p50_prev, _ = sc.quantiles(prev)
            rising = ((p50 - p50_prev) > 3.0) & mask if prev != at else np.zeros_like(mask)
            out["local"] = {
                "n_edges": int(mask.sum()),
                "wet_edges": int(((p50 > 5.0) & mask).sum()),
                "rising_edges": int(rising.sum()),
                "mean_depth_cm": round(float(p50[mask].mean()), 1),
                "max_depth_cm": round(float(p50[mask].max()), 1),
            }
    return out
