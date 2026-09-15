from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..deps import default_scene
from ..engine import state, router as eng_router

api = APIRouter(prefix="/v1")

class RouteRequest(BaseModel):
    origin: list[float] = Field(min_length=2, max_length=2)
    destination: list[float] = Field(min_length=2, max_length=2)
    waypoints: list[list[float]] = Field(default_factory=list, max_length=6)
    depart_tick: int
    vehicle: str
    risk_tolerance: float | None = None
    include_conservative: bool = False
    scene: str | None = None

@api.post("/routes")
def post_routes(req: RouteRequest) -> dict:
    sc = state.get(req.scene or default_scene())
    if req.vehicle not in eng_router.ENVELOPE:
        raise HTTPException(422, "unknown vehicle")
    if not 0 <= req.depart_tick < sc.T:
        raise HTTPException(422, f"depart_tick out of range 0..{sc.T - 1}")
    res = eng_router.route(sc, req.vehicle, tuple(req.origin),
                           tuple(req.destination), req.depart_tick,
                           include_conservative=req.include_conservative,
                           waypoints=req.waypoints)

    def pack(kind: str, r: dict | None) -> dict | None:
        if r is None:
            return None
        return {
            "kind": kind,
            "edge_ids": [sc.g.edge_ids[e] for e in r["edges"]],
            "geometry": eng_router.geometry(sc, r["edges"]),
            "travel_time_s": round(r["travel_time_s"], 1),
            "leg_times_s": r.get("leg_times_s", [round(r["travel_time_s"], 1)]),
            "risk_exposure_s": round(r["risk_exposure_s"], 1),
            "max_edge_risk": round(r["max_edge_risk"], 4),
        }

    routes = [x for x in (
        pack("fastest_dry", res["dry"]),
        pack("recommended", res["recommended"]),
        pack("most_conservative", res["conservative"]),
    ) if x]
    status = "ok" if res["recommended"] else "no_safe_route"

    comparison, explanation = {}, []
    if res["dry"] and res["recommended"]:
        comparison = {
            "added_time_s": round(res["recommended"]["travel_time_s"] - res["dry"]["travel_time_s"], 1),
            "avoided_exposure_s": round(res["dry"]["risk_exposure_s"] - res["recommended"]["risk_exposure_s"], 1),
        }
        # why: dry-route edges the recommendation refuses, with their reason codes
        from ..engine import passability
        full = passability.edge_states(sc, req.depart_tick, req.vehicle)
        rec_set = set(res["recommended"]["edges"])
        for e in res["dry"]["edges"]:
            if e not in rec_set and full["bands"][e] >= 2:      # uncertain or avoid
                explanation.append({
                    "edge_id": sc.g.edge_ids[e],
                    "reason_code": passability.edge_reasons(sc, req.depart_tick, req.vehicle, e)[0],
                    "detail": f"band={['low','unknown','uncertain','avoid'][full['bands'][e]]}, "
                              f"p50={full['p50_cm'][e]}cm, pi={full['pi'][e]}",
                })
            if len(explanation) >= 8:
                break
    return {"status": status, "routes": routes, "wait_suggestion": res["wait"],
            "n_legs": res["n_legs"],
            "comparison": comparison, "explanation": explanation,
            "is_synthetic": True, "evidence_class": "simulated"}
