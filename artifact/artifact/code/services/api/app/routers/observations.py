"""Community reports (M5). Raw imagery never reaches the server: the client sends a
derived interval + an already-blurred 64x64 thumbnail at most (invariant I7)."""
import base64
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..deps import default_scene, db
from ..engine import state

api = APIRouter(prefix="/v1")

CATEGORY_CM = {           # vehicle-aware buckets — nobody is asked to measure water
    "dry": (0.0, 3.0), "ankle": (3.0, 15.0), "footrest": (15.0, 30.0),
    "wheel_hub": (30.0, 50.0), "impassable": (50.0, 120.0),
}
MAX_THUMB_B64 = 12_000    # 64x64 jpeg fits well under this

class ObservationIn(BaseModel):
    edge_id: str
    tick: int
    category: str
    vehicle_context: str = "none"
    consent: bool
    location: list[float] | None = None
    thumb_b64: str | None = Field(default=None, max_length=MAX_THUMB_B64)
    scene: str | None = None

@api.post("/observations")
def post_observation(o: ObservationIn) -> dict:
    sc = state.get(o.scene or default_scene())
    if not o.consent:
        raise HTTPException(422, "consent required")
    if o.category not in CATEGORY_CM:
        raise HTTPException(422, "unknown category")
    if o.edge_id not in sc.g.idx:
        raise HTTPException(422, "unknown edge")
    if not 0 <= o.tick < sc.T:
        raise HTTPException(422, "tick out of range")
    e = sc.g.idx[o.edge_id]
    # anti-spoof: reported location must be near the edge (coarse gate)
    if o.location:
        ex, ey = sc.g.coords[e][0]
        if (o.location[0] - ex) ** 2 + (o.location[1] - ey) ** 2 > 0.01 ** 2:
            raise HTTPException(422, "location too far from reported edge")
    if o.thumb_b64:
        try:
            raw = base64.b64decode(o.thumb_b64, validate=True)
        except Exception:
            raise HTTPException(422, "thumbnail not valid base64")
        if len(raw) > 9_000:
            raise HTTPException(422, "thumbnail too large — raw images are not accepted")
    lo, hi = CATEGORY_CM[o.category]
    with sc.lock:
        sc.user_obs.append({
            "feed_id": f"user-{len(sc.user_obs)}", "source_class": "community",
            "edge": e, "tick": o.tick, "interval_cm": [lo, hi],
        })
    sc.bump()
    quality = 0.55 if o.thumb_b64 else 0.45        # thumbnail slightly raises trust
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO observations
                (edge_id, tick, source_class, category, depth_interval_cm_lo,
                 depth_interval_cm_hi, vehicle_context, quality_score, thumb_b64, is_synthetic)
                VALUES (%s,%s,'community',%s,%s,%s,%s,%s,%s,true)""",
                (o.edge_id, o.tick, o.category, lo, hi, o.vehicle_context, quality, o.thumb_b64))
            conn.commit()
    except Exception:
        pass  # DB persistence is best-effort in the demo; state update already applied
    return {"status": "accepted", "quality_score": quality,
            "privacy_transform": "client_blur_thumb64_v1",
            "interval_cm": [lo, hi], "is_synthetic": True}
