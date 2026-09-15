from fastapi import APIRouter
from ..deps import default_scene
from ..engine import state
from ..engine.passability import ENVELOPE

api = APIRouter(prefix="/v1")

@api.get("/model-card")
def model_card() -> dict:
    sc = state.get(default_scene())
    return {
        "name": "Duong An VN — demo passability engine",
        "model_version": f"demo-{sc.meta['spec_hash']}",
        "scope": "Bounded Thu Duc demo scene; SIMULATED compound rain-tide event; "
                 "OSSE design: simulated feeds drawn from a designated truth run.",
        "not_claimed": [
            "No real flood observation is shown as such (all states tagged simulated).",
            "No route is guaranteed safe; lower-risk is not zero-risk.",
            "No city-scale savings are claimed.",
        ],
        "envelopes_cm": {v: {"caution": c, "refuse": r} for v, (c, r) in ENVELOPE.items()},
        "physics_guards": sc.meta["guards"],
        "training_cutoff": "n/a (physics-prior baseline; no learned residual active)",
        "known_limitations": [
            "GLO-30 elevation is a coarse prior and cannot resolve curbs or alley microtopography.",
            "Drainage capacity is a latent prior, not measured pipe data.",
            "Flow velocity is not modelled; moving-water hazard is handled by conservative envelopes.",
            "Single simulated event; no cross-event validation in the demo.",
        ],
        "incident_status": "demo",
        "is_synthetic": True,
    }
