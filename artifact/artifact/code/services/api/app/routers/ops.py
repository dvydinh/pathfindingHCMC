import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..deps import default_scene, db, DATA
from ..engine import state, active

api = APIRouter(prefix="/v1/ops")

@api.get("/sensor-coverage")
def sensor_coverage(scene: str | None = None, feed_id: str | None = None) -> dict:
    """Which edges each sensor actually informs, and how strongly.

    Not an invented viewshed. The engine assimilates an observation across
    `Scenario.neighbourhood()` — up to three graph hops, constrained to the same basin,
    with a fixed hop decay — so *that* set is the sensor's real footprint. Reporting it
    lets the map show where the network genuinely sees and, more usefully, where it does
    not: an edge with zero weight is unobserved, whatever its static data_quality says.
    """
    s = scene or default_scene()
    sc = state.get(s)
    g = sc.g

    sensors: dict[str, dict] = {}
    for o in sc.meta["feeds"]:
        fid = o["feed_id"]
        if fid not in sensors:
            sensors[fid] = {"feed_id": fid, "source_class": o["source_class"],
                            "edge": o["edge"]}
    if feed_id is not None:
        if feed_id not in sensors:
            raise HTTPException(404, f"unknown feed {feed_id!r}")
        sensors = {feed_id: sensors[feed_id]}

    per_edge: dict[int, float] = {}
    per_edge_n: dict[int, int] = {}
    out_sensors = []
    for fid, meta in sensors.items():
        nbhd = sc.neighbourhood(meta["edge"])
        for e, w in nbhd.items():
            per_edge[e] = max(per_edge.get(e, 0.0), float(w))
            per_edge_n[e] = per_edge_n.get(e, 0) + 1
        anchor = meta["edge"]
        out_sensors.append({
            "feed_id": fid, "source_class": meta["source_class"],
            "anchor_edge_id": g.edge_ids[anchor],
            "anchor_street": g.name[anchor] or "",
            "lon": g.coords[anchor][0][0], "lat": g.coords[anchor][0][1],
            "n_edges_covered": len(nbhd),
            "covered_m": round(sum(float(g.length_m[e]) for e in nbhd), 1),
            "edges": ([{"edge_id": g.edge_ids[e], "weight": round(float(w), 2)}
                       for e, w in sorted(nbhd.items(), key=lambda kv: -kv[1])]
                      if feed_id is not None else None),
        })

    covered_m = sum(float(g.length_m[e]) for e in per_edge)
    total_m = float(g.length_m.sum())
    return {
        "scene": s, "feed_id": feed_id,
        "n_sensors": len(out_sensors),
        "sensors": sorted(out_sensors, key=lambda x: x["feed_id"]),
        "edge_weight": ({g.edge_ids[e]: round(w, 2) for e, w in per_edge.items()}
                        if feed_id is None else None),
        "edge_sensor_count": ({g.edge_ids[e]: n for e, n in per_edge_n.items()}
                              if feed_id is None else None),
        "n_edges_covered": len(per_edge),
        "n_edges_total": g.n,
        "pct_edges_covered": round(100.0 * len(per_edge) / g.n, 1),
        "pct_length_covered": round(100.0 * covered_m / total_m, 1),
        "model": {"max_hops": 3, "hop_decay": [1.0, 0.6, 0.35, 0.2],
                  "constraint": "same basin (|dz| < BASIN_DZ)"},
        "note": ("Trọng số là mức ảnh hưởng của quan trắc lên cạnh đó trong đồng hoá, "
                 "không phải tầm nhìn quang học của camera."),
        "evidence_class": "simulated",
        "is_synthetic": True,
    }


@api.get("/feeds")
def feeds(at: int = 0, scene: str | None = None) -> dict:
    sc = state.get(scene or default_scene())
    by_feed: dict[str, dict] = {}
    for o in sc.meta["feeds"]:
        f = by_feed.setdefault(o["feed_id"], {
            "feed_id": o["feed_id"], "source_class": o["source_class"],
            "edge_id": sc.g.edge_ids[o["edge"]], "last_tick": -1, "n_obs": 0,
        })
        if o["tick"] <= at:
            f["n_obs"] += 1
            f["last_tick"] = max(f["last_tick"], o["tick"])
    for f in by_feed.values():
        f["outage"] = f["feed_id"] in sc.outages
        f["age_s"] = (at - f["last_tick"]) * sc.tick_s if f["last_tick"] >= 0 else None
        f["status"] = ("outage" if f["outage"]
                       else "stale" if f["age_s"] is not None and f["age_s"] > 1800
                       else "ok" if f["age_s"] is not None else "pending")
    return {"tick": at, "feeds": sorted(by_feed.values(), key=lambda x: x["feed_id"]),
            "guards": sc.meta["guards"], "user_reports": len(sc.user_obs),
            "closures": [sc.g.edge_ids[e] for e in sc.closures],
            "is_synthetic": True}

@api.get("/queue")
def sensing_queue(at: int, scene: str | None = None) -> dict:
    sc = state.get(scene or default_scene())
    if not 0 <= at < sc.T:
        raise HTTPException(422, "tick out of range")
    return {"tick": at, "queue": active.queue(sc, at), "is_synthetic": True}

class Toggle(BaseModel):
    edge_id: str | None = None
    feed_id: str | None = None
    active: bool
    scene: str | None = None

@api.post("/closure")
def closure(t: Toggle) -> dict:
    sc = state.get(t.scene or default_scene())
    if not t.edge_id or t.edge_id not in sc.g.idx:
        raise HTTPException(422, "unknown edge")
    e = sc.g.idx[t.edge_id]
    with sc.lock:
        (sc.closures.add if t.active else sc.closures.discard)(e)
    sc.bump()
    _log("closure", t.edge_id, t.active)
    return {"status": "ok", "closures": [sc.g.edge_ids[x] for x in sc.closures]}

@api.post("/outage")
def outage(t: Toggle) -> dict:
    sc = state.get(t.scene or default_scene())
    known = {o["feed_id"] for o in sc.meta["feeds"]}
    if not t.feed_id or t.feed_id not in known:
        raise HTTPException(422, "unknown feed")
    with sc.lock:
        (sc.outages.add if t.active else sc.outages.discard)(t.feed_id)
    sc.bump()
    _log("outage", t.feed_id, t.active)
    return {"status": "ok", "outages": sorted(sc.outages)}

@api.get("/replay-metrics")
def replay_metrics() -> dict:
    p = DATA / "eval" / "replay_metrics.json"
    if not p.exists():
        return {"status": "not_computed",
                "hint": "run `make eval` to produce the routing benchmark"}
    return json.loads(p.read_text(encoding="utf-8"))

def _log(kind: str, target: str, active: bool) -> None:
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO override_log (kind, target, active) VALUES (%s,%s,%s)",
                        (kind, target, active))
            conn.commit()
    except Exception:
        pass

@api.get("/override-log")
def override_log() -> list[dict]:
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT kind, target, active, at FROM override_log ORDER BY at DESC LIMIT 50")
            return [{"kind": k, "target": t, "active": a, "at": str(ts)}
                    for k, t, a, ts in cur.fetchall()]
    except Exception:
        return []

@api.post("/reset")
def reset(scene: str | None = None) -> dict:
    """Demo/rehearsal reset: clear closures, outages, and user reports."""
    sc = state.get(scene or default_scene())
    with sc.lock:
        sc.closures.clear(); sc.outages.clear(); sc.user_obs.clear()
    sc.bump()
    return {"status": "reset"}
