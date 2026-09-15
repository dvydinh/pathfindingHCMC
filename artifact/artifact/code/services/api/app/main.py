"""Duong An VN API."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import scene, tiles, passability, routes, observations, ops, modelcard, provenance, weather, assistant, environment, charging

# ---------------------------------------------------------------------------
# Demo scope gate.
#
# The demo is cut to one value chain: PREDICT FLOOD -> UPDATE ROAD STATE -> RECOMMEND
# ROUTE. Everything off this chain is switched off here rather than deleted, so the code
# stays reviewable and a flag flip restores it. Nothing below changes engine behaviour;
# this is a mount-layer decision only.
#
# Override from the environment for a one-off demo, e.g.
#   DEMO_FEATURES="charging=1,tiles=1" uvicorn app.main:app
# ---------------------------------------------------------------------------
DEMO_FEATURES: dict[str, bool] = {
    # --- spine: the value chain itself ---
    "scene": True,            # GET /v1/scene, /v1/edges.geojson — map geometry
    "passability": True,      # GET /v1/state, /v1/passability — road state per tick
    "routes": True,           # POST /v1/routes — the recommendation
    "observations": True,     # POST /v1/observations — community reports feed assimilation
    "weather": True,          # GET /v1/weather — rain + tide, the forcing of the prediction
    "assistant": True,        # POST /v1/assistant — conversational access to the same engine

    # --- official closure: the authoritative flood signal, kept ---
    "ops_closure": True,      # POST /v1/ops/closure, GET /v1/ops/feeds, /override-log, /reset

    # --- credibility, zero runtime cost, keeps the demo honest about its limits ---
    "modelcard": True,        # GET /v1/model-card
    "provenance": True,       # GET /v1/provenance/{edge_id}
    "ops_sensor_coverage": True,   # GET /v1/ops/sensor-coverage — the 0.8% coverage argument

    # --- off: real features, off the value chain, code retained ---
    "ops_sensor_outage": False,    # POST /v1/ops/outage — sensor-failure drill
    "ops_sensing_queue": False,    # GET /v1/ops/queue — active-sensing (engine/active.py)
    "ops_replay_metrics": False,   # GET /v1/ops/replay-metrics — needs `make eval`
    "environment": False,          # ambient air/heat; feeds nothing in passability or routing
    "charging": False,             # EV charging reachability
    "tiles": False,                # MVT from PostGIS; the UI reads /v1/edges.geojson instead
}


def _apply_env_overrides(flags: dict[str, bool]) -> dict[str, bool]:
    """DEMO_FEATURES="charging=1,tiles=0" — unknown names are ignored, not fatal."""
    raw = os.environ.get("DEMO_FEATURES", "").strip()
    if not raw:
        return flags
    for part in raw.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k in flags:
            flags[k] = v.strip().lower() in ("1", "true", "yes", "on")
    return flags


FEATURES = _apply_env_overrides(dict(DEMO_FEATURES))

# Endpoints gated individually because they share a router with a spine endpoint.
# routers/ops.py mounts official closures (spine) and the sensor-outage drill (off-scope)
# on the same APIRouter, so the gate has to be per-path rather than per-router.
_OPS_GATED: list[tuple[str, str, str]] = [
    ("ops_sensor_outage", "POST", "/v1/ops/outage"),
    ("ops_sensing_queue", "GET", "/v1/ops/queue"),
    ("ops_replay_metrics", "GET", "/v1/ops/replay-metrics"),
    ("ops_sensor_coverage", "GET", "/v1/ops/sensor-coverage"),
]

app = FastAPI(title="Duong An VN", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local demo only
    allow_methods=["*"],
    allow_headers=["*"],
)

for _flag, _router in (
    ("scene", scene.router),
    ("tiles", tiles.router),
    ("passability", passability.router),
    ("routes", routes.api),
    ("observations", observations.api),
    ("modelcard", modelcard.api),
    ("provenance", provenance.api),
    ("weather", weather.api),
    ("assistant", assistant.api),
    ("environment", environment.api),
    ("charging", charging.api),
):
    if FEATURES[_flag]:
        app.include_router(_router)

# ops is mixed: mount it if ANY of its parts is on, then drop the gated-off paths.
if FEATURES["ops_closure"] or any(FEATURES[f] for f, _, _ in _OPS_GATED):
    app.include_router(ops.api)
    _drop = {(m, p) for f, m, p in _OPS_GATED if not FEATURES[f]}
    if not FEATURES["ops_closure"]:
        _drop |= {("POST", "/v1/ops/closure"), ("GET", "/v1/ops/feeds"),
                  ("GET", "/v1/ops/override-log"), ("POST", "/v1/ops/reset")}
    app.router.routes = [
        r for r in app.router.routes
        if not any(getattr(r, "path", None) == p and m in getattr(r, "methods", set())
                   for m, p in _drop)
    ]


@app.get("/v1/features")
def features() -> dict:
    """What this build actually serves. A reviewer should not have to infer the demo
    scope from which buttons happen to be visible."""
    return {"features": FEATURES,
            "scope": "predict flood -> update road state -> recommend route",
            "note": "disabled features are switched off at the mount layer, not removed"}


@app.on_event("startup")
def _warm() -> None:
    import threading
    from .deps import default_scene
    threading.Thread(target=passability.warm, args=(default_scene(),), daemon=True).start()

@app.get("/healthz")
def healthz() -> dict:
    """Liveness, plus whether persistence is actually available.

    Three write paths (citizen reports, closure/outage audit entries) swallow database
    errors so the demo keeps working without PostGIS. That is the right call for a demo
    and the wrong thing to leave invisible: a reviewer running without Docker would see an
    empty override log and reasonably conclude the audit trail is broken rather than
    absent. Reporting the connection turns a silent degradation into a stated one.
    """
    from .deps import db
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        persistence = True
    except Exception:
        persistence = False
    return {"status": "ok", "service": "duong-an-vn-api",
            "persistence": persistence,
            "degraded": [] if persistence else [
                "observations apply to live state but are not stored",
                "closures and outages take effect but are not audit-logged",
                "/v1/ops/override-log returns empty",
                "/v1/tiles/{z}/{x}/{y}.mvt is unavailable (the map uses /v1/edges.geojson)",
            ]}
