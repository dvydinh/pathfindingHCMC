"""EV charging stations and whether the simulated flood cuts off their approach."""
from fastapi import APIRouter, HTTPException
from ..deps import default_scene
from ..engine import charging, router as eng_router, state

api = APIRouter(prefix="/v1")


@api.get("/charging")
def charging_stations(at: int = 0, vehicle: str = "e_2w",
                      scene: str | None = None) -> dict:
    s = scene or default_scene()
    if vehicle not in eng_router.ENVELOPE:
        raise HTTPException(422, f"unknown vehicle {vehicle!r}")
    sc = state.get(s)
    snap = charging.snapshot(sc, s, at, vehicle)
    if snap is None:
        raise HTTPException(503, "charging data unavailable: run scripts/fetch_charging.py")
    return snap
