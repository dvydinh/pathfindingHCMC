from fastapi import APIRouter, HTTPException
from ..deps import default_scene
from ..engine import state

api = APIRouter(prefix="/v1")

@api.get("/provenance/{edge_id}")
def provenance(edge_id: str, at: int = 0, scene: str | None = None) -> dict:
    sc = state.get(scene or default_scene())
    if edge_id not in sc.g.idx:
        raise HTTPException(404, "unknown edge")
    e = sc.g.idx[edge_id]
    mix = sc.source_mix(at, e)
    last = int(sc.last_obs_tick(at)[e])
    return {
        "edge_id": edge_id, "edge_version": 1,
        "static_attributes": "inferred (OSM geometry + GLO-30 terrain)",
        "dynamic_state": "simulated (OSSE scenario)",
        "source_mix": mix,
        "last_observation_tick": last if last >= 0 else None,
        "evidence_age_s": (at - last) * sc.tick_s if last >= 0 else None,
        "is_synthetic": True,
    }
