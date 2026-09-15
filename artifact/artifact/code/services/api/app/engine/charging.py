"""EV charging stations, and whether the flood event cuts them off.

Two provenance classes live in one payload here, and keeping them apart is the point:

* **Where a station is** — real, from OpenStreetMap.
* **Whether it is reachable right now** — simulated, from the storm scenario.

The second is the useful part for an `e_2w` rider: a charger that exists but sits behind an
avoid-band segment is not a charger you can use at that tick.

A finding that shaped this module: OSM currently maps **no** charging station inside either
demo bbox, with the nearest 7.5 km from the Thu Duc centre. So the API distinguishes an
empty *scene* from an empty *world* and always carries the nearest known stations plus a
coverage note. An empty map that silently reads as "nowhere to charge" would be a worse
lie than no feature at all.
"""
from __future__ import annotations
import functools
import json

from ..deps import DATA
from . import narrate, passability, router as eng_router
from .state import Scenario

# How far a station may sit from a mapped road before we decline to reason about access.
ACCESS_SNAP_M = eng_router.SNAP_MAX_M


@functools.lru_cache(maxsize=4)
def load(scene: str) -> dict | None:
    path = DATA / "raw" / f"{scene}.charging.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _access_state(sc: Scenario, station: dict, tick: int, vehicle: str) -> dict:
    """Risk of the mapped road segment a rider would actually arrive on.

    Bounded snapping, same rule as routing: a station more than ACCESS_SNAP_M from any
    mapped road gets no risk claim at all rather than one borrowed from a distant street.
    """
    node, dist_m = eng_router.snap_checked(sc, station["lon"], station["lat"])
    if node is None:
        return {"access_known": False, "nearest_road_m": round(dist_m),
                "why": "không có đoạn đường nào được ánh xạ đủ gần để nói về lối vào"}
    # Any edge leaving that node is a candidate approach; the worst one governs, since a
    # rider must survive the approach they actually take (I2).
    edges = sc.g.out_edges.get(node, [])
    if not edges:
        return {"access_known": False, "nearest_road_m": round(dist_m),
                "why": "nút đường gần nhất không có cạnh đi ra"}
    st = passability.edge_states(sc, tick, vehicle)
    worst = min(edges, key=lambda e: float(st["pi"][e]))
    band = narrate.BAND_NAMES[st["bands"][worst]]
    return {
        "access_known": True,
        "nearest_road_m": round(dist_m),
        "access_edge_id": sc.g.edge_ids[worst],
        "access_street": sc.g.name[worst] or narrate.UNNAMED_VI,
        "risk_band": band, "risk_band_vi": narrate.BAND_VI[band],
        "pi_passable": round(float(st["pi"][worst]), 3),
        "depth_p50_cm": round(float(st["p50_cm"][worst]), 1),
        **narrate._evidence(st["age_s"][worst]),
        "reasons": passability.edge_reasons(sc, tick, vehicle, worst),
        # This half of the payload comes from the synthetic storm, unlike the location.
        "evidence_class": "simulated",
    }


def snapshot(sc: Scenario, scene: str, tick: int, vehicle: str,
             nearest: int = 6) -> dict | None:
    data = load(scene)
    if data is None:
        return None
    tick = max(0, min(int(tick), sc.T - 1))

    in_scene, outside = [], []
    for station in data["stations"]:
        entry = {k: station[k] for k in (
            "osm_id", "name", "operator", "capacity", "sockets", "access", "fee",
            "lon", "lat", "in_scene", "km_from_scene_centre", "bearing_from_scene_vi")}
        if station["in_scene"]:
            entry["access"] = _access_state(sc, station, tick, vehicle)
            in_scene.append(entry)
        else:
            entry["routing_available"] = False
            entry["why_no_routing"] = ("nằm ngoài vùng demo — engine chỉ dựng đồ thị "
                                       "trong bbox nên không tính được tuyến tới đây")
            outside.append(entry)

    usable = [s for s in in_scene
              if s["access"].get("access_known") and s["access"]["risk_band"] == "low"]
    return {
        "scene": scene, "tick": tick, "vehicle": vehicle,
        "n_in_scene": len(in_scene),
        "n_usable_now": len(usable),
        "stations": in_scene,
        "nearest_outside_scene": outside[:nearest],
        "buffer_km": data.get("buffer_km"),
        "source": data.get("source", {}),
        # Locations are real OSM; reachability comes from the simulated storm.
        "location_evidence_class": "real geometry",
        "access_evidence_class": "simulated",
        "coverage_note": data.get("coverage_note", ""),
        "no_station_mapped_in_scene": len(in_scene) == 0,
        "units": {"km_from_scene_centre": "kilometres", "nearest_road_m": "metres",
                  "depth_p50_cm": "centimetres",
                  "pi_passable": "probability 0-1 that the approach segment is passable"},
    }
