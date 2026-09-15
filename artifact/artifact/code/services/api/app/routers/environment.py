"""Ambient conditions endpoint: temperature, humidity, PM2.5/PM10, dust, AQI, UV.

Real Open-Meteo data on the real clock, kept deliberately separate from the simulated
flood layer and its scenario ticks (see engine/environment.py). Read-only, and it feeds
nothing in the passability or routing path.
"""
from fastapi import APIRouter, HTTPException
from ..deps import default_scene
from ..engine import environment as env

api = APIRouter(prefix="/v1")


@api.get("/environment")
def environment(hour: int = 0, scene: str | None = None) -> dict:
    """One hour of the vendored ambient series, per source cell plus render tiles."""
    s = scene or default_scene()
    snap = env.snapshot(s, hour)
    if snap is None:
        raise HTTPException(
            503, "ambient layer unavailable: run scripts/fetch_env.py for this scene")
    return snap


@api.get("/environment/series")
def environment_series(metric: str, scene: str | None = None) -> dict:
    """Scene-mean series for one metric, for the sparkline in the panel."""
    s = scene or default_scene()
    out = env.series(s, metric)
    if out is None:
        raise HTTPException(422, f"unknown metric {metric!r}; "
                                 f"known: {', '.join(env.METRICS)}")
    return out
