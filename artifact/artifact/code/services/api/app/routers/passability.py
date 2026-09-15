from fastapi import APIRouter, HTTPException, Response
import orjson
from ..deps import default_scene
from ..engine import state, passability

router = APIRouter(prefix="/v1")
_bytes_cache: dict = {}

def warm(scene_name: str) -> None:
    """Background warm-up: precompute every tick for every vehicle so scrubbing and
    vehicle switches are instant. Bails out cheaply if state version changes."""
    try:
        sc = state.get(scene_name)
    except Exception:
        return
    from ..engine import router as eng_router
    eng_router._snap_index(sc)                      # build the SCC snap core up front
    for vehicle in ("motorbike", "car", "e_2w", "response"):
        for t in range(sc.T):
            v0 = sc.version
            key = (scene_name, t, vehicle, v0)
            eng_router._tick_layer(sc, vehicle, t)  # route-cost layer
            if key in _bytes_cache:
                continue
            b = orjson.dumps(passability.edge_states(sc, t, vehicle))
            if sc.version == v0:
                _bytes_cache[key] = b

@router.get("/state")
def get_state(at: int, vehicle: str = "motorbike", scene: str | None = None) -> Response:
    """Compact aligned-array scene state (order matches /v1/edges.geojson)."""
    s = scene or default_scene()
    sc = state.get(s)
    if not 0 <= at < sc.T:
        raise HTTPException(422, f"tick out of range 0..{sc.T - 1}")
    if vehicle not in passability.ENVELOPE:
        raise HTTPException(422, "unknown vehicle")
    key = (s, at, vehicle, sc.version)
    if key not in _bytes_cache:
        while len(_bytes_cache) > 96:
            del _bytes_cache[next(iter(_bytes_cache))]
        _bytes_cache[key] = orjson.dumps(passability.edge_states(sc, at, vehicle))
    return Response(_bytes_cache[key], media_type="application/json")

@router.get("/passability")
def get_passability(at: int, vehicle: str = "motorbike", edge_id: str | None = None,
                    scene: str | None = None) -> dict:
    """Detailed EdgeState — single edge (inspector) or capped list."""
    s = scene or default_scene()
    sc = state.get(s)
    if not 0 <= at < sc.T:
        raise HTTPException(422, f"tick out of range 0..{sc.T - 1}")
    full = passability.edge_states(sc, at, vehicle)
    def detail(e: int) -> dict:
        rank = ["low", "unknown", "uncertain", "avoid"]
        # depth fan over time for the inspector chart
        fan = []
        for t in range(0, sc.T, 2):
            p10, p50, p90 = sc.quantiles(t)
            fan.append({"tick": t, "p10": round(float(p10[e]), 1),
                        "p50": round(float(p50[e]), 1), "p90": round(float(p90[e]), 1)})
        return {
            "edge_id": sc.g.edge_ids[e], "edge_version": 1,
            "depth_q": {"p10": None, "p50": full["p50_cm"][e], "p90": None,
                        "width": full["width_cm"][e]},
            "pi": full["pi"][e],
            "risk_band": rank[full["bands"][e]],
            "evidence_class": "simulated",
            "evidence_age_s": full["age_s"][e],
            "source_mix": sc.source_mix(at, e),
            "reason_codes": passability.edge_reasons(sc, at, vehicle, e),
            "is_synthetic": True,
            "fan": fan,
        }
    if edge_id is not None:
        if edge_id not in sc.g.idx:
            raise HTTPException(404, "unknown edge")
        return {"model_version": full["model_version"], "tick": at,
                "edges": [detail(sc.g.idx[edge_id])]}
    # capped list of the most at-risk edges
    import numpy as np
    order = np.argsort(full["pi"])[:200]
    return {"model_version": full["model_version"], "tick": at,
            "edges": [detail(int(e)) for e in order[:50]]}
