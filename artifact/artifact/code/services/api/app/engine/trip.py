"""Deterministic map-tool orchestration for multi-stop and comparative trips.

This is the lower tier of a two-tier design: the language model is the planner — it
decides *which* trip to ask about and how to phrase the answer — while every map
operation below is executed here, in code, with no model in the loop. Decomposition that
a tool-calling loop would spend one model round-trip per step on (resolve stop, resolve
stop, resolve stop, route, re-route at another time) collapses into a single call whose
fan-out is fixed and auditable.

The safety argument is unchanged from the single-leg path and is the reason the fan-out
lives here rather than in the model: resolution, bbox validation and bounded snapping run
for every stop, and a trip is refused whole if any stop fails. A comparison is only ever a
report of what the engine computed for each variant; it never becomes encouragement to
travel on a variant that fails the chance constraint.
"""
from __future__ import annotations
from . import gazetteer, narrate, router as eng_router
from .state import Scenario

MAX_STOPS = 6            # matches the waypoint cap on POST /v1/routes
MAX_VARIANTS = 6         # base + comparisons; bounds worst-case latency (~365 ms each)


def resolve_stops(scene: str, stops: list[str]) -> tuple[list | None, dict | None]:
    """Resolve every stop up front. Returns (resolved, None) or (None, error).

    All-or-nothing on purpose: a partially resolved trip invites the model to fill the
    gap from its own knowledge, which is exactly the channel this design removes.
    """
    if len(stops) < 2:
        return None, {"status": "invalid_trip", "reason": "need_at_least_two_stops"}
    if len(stops) > MAX_STOPS:
        return None, {"status": "invalid_trip", "reason": "too_many_stops",
                      "max_stops": MAX_STOPS}
    out = []
    for i, name in enumerate(stops):
        r = gazetteer.resolve(scene, name)
        if r["status"] != "ok":
            err = {"status": r["status"], "stop_index": i, "query": name,
                   "candidates": r.get("candidates", []),
                   "instruction": ("Hỏi người dùng làm rõ điểm dừng này; không tự chọn, "
                                   "không bỏ qua nó, không tự suy ra từ kiến thức của bạn.")}
            if r.get("did_you_mean"):
                err["names_that_look_similar"] = r["did_you_mean"]
                err["warning_about_similar_names"] = (
                    "ĐÂY KHÔNG PHẢI địa điểm người dùng hỏi — chỉ là tên na ná trong "
                    "vùng demo. KHÔNG được dùng thay cho điểm dừng đã hỏi.")
            return None, err
        out.append(r["candidates"][0])
    return out, None


def validate_stops(sc: Scenario, bbox: list, resolved: list) -> dict | None:
    """Bbox + bounded-snap check for every stop; returns an error payload or None."""
    for i, p in enumerate(resolved):
        if not (bbox[0] <= p["lon"] <= bbox[2] and bbox[1] <= p["lat"] <= bbox[3]):
            return {"status": "out_of_area", "stop_index": i, "place": p["name"],
                    "instruction": "Ngoài vùng demo; nói rõ với người dùng."}
        node, dist_m = eng_router.snap_checked(sc, p["lon"], p["lat"])
        if node is None:
            return {"status": "no_road_nearby", "stop_index": i, "place": p["name"],
                    "nearest_road_m": round(dist_m),
                    "instruction": (f"Không có đoạn đường nào trong "
                                    f"{eng_router.SNAP_MAX_M:.0f} m quanh điểm này.")}
    return None


def _variant(sc: Scenario, resolved: list, vehicle: str, tick: int) -> dict:
    """One routing run over the stop chain, summarised without geometry."""
    pts = [(p["lon"], p["lat"]) for p in resolved]
    res = eng_router.route(sc, vehicle, pts[0], pts[-1], tick,
                           waypoints=[list(p) for p in pts[1:-1]])
    out = {"depart_tick": tick, "vehicle": vehicle, "n_legs": res["n_legs"],
           "status": "ok" if res["recommended"] else "no_safe_route"}
    for key, r in (("fastest_dry", res["dry"]), ("recommended", res["recommended"])):
        if r:
            out[key] = {"travel_min": round(r["travel_time_s"] / 60, 1),
                        "risk_exposure_s": round(r["risk_exposure_s"], 1)}
    if res["dry"] and res["recommended"]:
        out["added_min"] = round(
            (res["recommended"]["travel_time_s"] - res["dry"]["travel_time_s"]) / 60, 1)
    if res["wait"]:
        out["wait_suggestion"] = {
            "depart_tick": res["wait"]["depart_tick"],
            "in_minutes": (res["wait"]["depart_tick"] - tick) * sc.tick_s // 60,
            "reason": res["wait"]["reason"]}
    return out, res


def plan(sc: Scenario, scene: str, bbox: list, stops: list[str], depart_tick: int,
         vehicle: str, compare_departures: list | None = None,
         compare_vehicles: list | None = None) -> tuple[dict, dict | None]:
    """Plan one multi-stop trip plus optional comparison variants.

    Returns (payload_for_the_model, base_route_result_or_None). The second value carries
    the geometry for the map; it is deliberately not part of the model-facing payload.
    """
    resolved, err = resolve_stops(scene, stops)
    if err:
        return err, None
    err = validate_stops(sc, bbox, resolved)
    if err:
        return err, None

    tick = max(0, min(int(depart_tick), sc.T - 1))
    base, base_res = _variant(sc, resolved, vehicle, tick)

    payload = {
        "stops": [{"name": p["name"], "kind_vi": p["kind_vi"],
                   "match_score": p["match_score"], "source": p["source"]}
                  for p in resolved],
        "plan": base,
    }
    shown = base_res["recommended"] or base_res["dry"]
    if shown:
        payload["streets_on_route"] = narrate.street_sequence(sc, shown["edges"], tick)
    if base_res["dry"] and base_res["recommended"]:
        payload["avoided_streets"] = narrate.avoided_streets(
            sc, base_res["dry"]["edges"], base_res["recommended"]["edges"], vehicle, tick)

    # ---- comparison variants -------------------------------------------------
    # Run in sequence, not concurrently: the scenario keeps a shared mutable layer cache
    # with size-bounded eviction, so parallel routing would race it. The win being claimed
    # here is one model round-trip instead of N, not wall-clock parallelism.
    variants, dropped = [], 0
    wanted: list[tuple[str, int]] = []
    for t in (compare_departures or []):
        t = max(0, min(int(t), sc.T - 1))
        if t != tick:
            wanted.append((vehicle, t))
    for v in (compare_vehicles or []):
        if v in eng_router.ENVELOPE and v != vehicle:
            wanted.append((v, tick))
    seen = {(vehicle, tick)}
    for v, t in wanted:
        if (v, t) in seen:
            continue
        if len(variants) + 1 >= MAX_VARIANTS:
            dropped += 1
            continue
        seen.add((v, t))
        var, _ = _variant(sc, resolved, v, t)
        variants.append(var)
    if variants:
        payload["comparisons"] = variants
        compliant = [v for v in [base] + variants if v["status"] == "ok"]
        payload["comparison_note"] = (
            "Chỉ so sánh những phương án ĐẠT chuẩn an toàn; phương án no_safe_route "
            "không phải lựa chọn, kể cả khi nhanh hơn."
        )
        if compliant:
            best = min(compliant, key=lambda v: (v.get("recommended", {})
                                                  .get("risk_exposure_s", 1e9),
                                                 v.get("recommended", {})
                                                  .get("travel_min", 1e9)))
            payload["lowest_exposure_option"] = {
                "depart_tick": best["depart_tick"], "vehicle": best["vehicle"]}
        else:
            payload["lowest_exposure_option"] = None
    if dropped:
        payload["comparisons_dropped"] = dropped
        payload["comparisons_cap"] = MAX_VARIANTS

    if base["status"] == "no_safe_route":
        payload["instruction"] = (
            "KHÔNG có tuyến đạt chuẩn an toàn cho chuyến này. Con số trong fastest_dry là "
            "tuyến nhanh nhất khi KHÔNG xét ngập — nó KHÔNG đạt chuẩn, nên không được nêu "
            "như một lựa chọn hay một ước lượng thời gian đi được. Chỉ nói rõ là không có "
            "tuyến an toàn, và nêu wait_suggestion nếu có.")
    payload["units"] = {"travel_min": "minutes", "risk_exposure_s": "seconds exposed",
                        "added_min": "minutes added vs fastest route"}
    payload["is_synthetic"] = True
    return payload, base_res
