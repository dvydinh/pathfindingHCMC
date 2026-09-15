"""Engine results -> named, unit-annotated facts for the conversational layer.

Every string a reply can contain about geography originates here, computed from engine
state, so the model narrates rather than invents. The shape follows the "perception
script" pattern from grounded-agent work on hazard response: a compact, explicitly
unit-annotated digest instead of raw geometry, which no LLM reads reliably.

Nothing in this module decides safety; it only renames and aggregates what the
passability and routing engines already produced.
"""
from __future__ import annotations
from collections import defaultdict
from . import passability
from .state import Scenario

BAND_NAMES = ["low", "unknown", "uncertain", "avoid"]
NO_EVIDENCE = -1          # engine sentinel: nothing has ever been observed on this edge
BAND_VI = {"low": "ít rủi ro", "unknown": "chưa biết",
           "uncertain": "không chắc", "avoid": "nên tránh"}
UNNAMED_VI = "đường không tên trong OSM"


def _evidence(age_s) -> dict:
    """A raw -1 reads as a negative age to a language model. Say what it means instead."""
    age = int(age_s)
    return ({"evidence_age_s": age} if age >= 0
            else {"evidence_age_s": None, "no_evidence_yet": True})


def _arrival_ticks(sc: Scenario, edges: list[int], depart_tick: int) -> list[int]:
    """Tick at which the traveller reaches each edge — the same time-propagation the
    router used, so narration and routing never disagree about *when*."""
    tt = sc.g.travel_time_s()
    ticks, t = [], 0.0
    for e in edges:
        ticks.append(min(depart_tick + int(t // sc.tick_s), sc.T - 1))
        t += float(tt[e])
    return ticks


def street_sequence(sc: Scenario, edges: list[int], depart_tick: int,
                    max_items: int = 12) -> list[dict]:
    """Consecutive edges collapsed into named runs, with distance and elapsed minutes."""
    g = sc.g
    tt = g.travel_time_s()
    ticks = _arrival_ticks(sc, edges, depart_tick)
    runs: list[dict] = []
    elapsed = 0.0
    for e, tk in zip(edges, ticks):
        nm = g.name[e] or ""
        if runs and runs[-1]["_raw"] == nm:
            runs[-1]["length_m"] += float(g.length_m[e])
        else:
            runs.append({"_raw": nm, "name": nm or UNNAMED_VI,
                         "length_m": float(g.length_m[e]),
                         "at_minute": round(elapsed / 60, 1), "arrival_tick": tk})
        elapsed += float(tt[e])
    for r in runs:
        r["length_m"] = round(r["length_m"], 1)
        r.pop("_raw")
    if len(runs) <= max_items:
        return runs
    # Keep the longest runs; a turn list is not the point, the recognisable roads are.
    keep = sorted(sorted(runs, key=lambda r: -r["length_m"])[:max_items],
                  key=lambda r: r["at_minute"])
    return keep


def avoided_streets(sc: Scenario, dry_edges: list[int], rec_edges: list[int],
                    vehicle: str, depart_tick: int, limit: int = 4) -> list[dict]:
    """Named roads the fastest route uses that the recommended route gives up, and the
    engine's reason for each. This is what makes 'né đường X' a fact, not a flourish."""
    g = sc.g
    rec = set(rec_edges)
    ticks = _arrival_ticks(sc, dry_edges, depart_tick)
    worst: dict[str, dict] = {}
    for e, tk in zip(dry_edges, ticks):
        if e in rec:
            continue
        nm = g.name[e]
        if not nm:
            continue
        st = passability.edge_states(sc, tk, vehicle)
        band = BAND_NAMES[st["bands"][e]]
        if band == "low":
            continue
        pi = float(st["pi"][e])
        cur = worst.get(nm)
        if cur is None or pi > cur["pi"]:
            worst[nm] = {
                "street": nm, "risk_band": band, "risk_band_vi": BAND_VI[band],
                "pi_passable": round(pi, 3),
                "depth_p50_cm": round(float(st["p50_cm"][e]), 1),
                **_evidence(st["age_s"][e]),
                "at_tick": tk,
                "reasons": passability.edge_reasons(sc, tk, vehicle, e),
            }
    return sorted(worst.values(), key=lambda d: d["pi_passable"])[:limit]


def street_state(sc: Scenario, edge_ids: list[str], name: str, tick: int,
                 vehicle: str) -> dict:
    """Aggregate one named street: worst segment drives the summary (I2 — uncertainty
    must never render safer than its parts)."""
    g = sc.g
    idxs = [g.idx[eid] for eid in edge_ids if eid in g.idx]
    if not idxs:
        return {"error": "street has no edges in this scene", "street": name}
    st = passability.edge_states(sc, tick, vehicle)
    counts: dict[str, int] = defaultdict(int)
    worst_e, worst_pi = idxs[0], 2.0
    total_m = 0.0
    for e in idxs:
        band = BAND_NAMES[st["bands"][e]]
        counts[band] += 1
        total_m += float(g.length_m[e])
        pi = float(st["pi"][e])
        if pi < worst_pi:
            worst_pi, worst_e = pi, e
    order = {"avoid": 0, "uncertain": 1, "unknown": 2, "low": 3}
    overall = min(counts, key=lambda b: order[b])
    return {
        "street": name, "tick": tick, "vehicle": vehicle,
        "length_m": round(total_m, 1), "n_segments": len(idxs),
        "overall_band": overall, "overall_band_vi": BAND_VI[overall],
        "segments_by_band": dict(counts),
        "worst_segment": {
            "edge_id": g.edge_ids[worst_e],
            "pi_passable": round(worst_pi, 3),
            "depth_p50_cm": round(float(st["p50_cm"][worst_e]), 1),
            **_evidence(st["age_s"][worst_e]),
            "reasons": passability.edge_reasons(sc, tick, vehicle, worst_e),
        },
        "units": {"length_m": "metres", "depth_p50_cm": "centimetres",
                  "evidence_age_s": "seconds since last evidence, null if never observed",
                  "pi_passable": "probability 0-1"},
        # Same provenance label area_summary already carries: every depth in this payload
        # comes from the synthetic storm ensemble, not from a measurement.
        "evidence_class": "simulated",
        "is_synthetic": True,
    }


def area_summary(sc: Scenario, tick: int, vehicle: str, top_n: int = 6) -> dict:
    """Scene-wide digest: band counts plus the worst *named* streets right now.

    Replaces handing the model any geometry — 25k edges never enter a prompt, and the
    model cannot rank roads it was never shown.
    """
    g = sc.g
    st = passability.edge_states(sc, tick, vehicle)
    access = g.access[vehicle]
    counts: dict[str, int] = defaultdict(int)
    by_street: dict[str, dict] = {}
    no_access_streets: set[str] = set()
    for e in range(g.n):
        band = BAND_NAMES[st["bands"][e]]
        counts[band] += 1
        nm = g.name[e]
        if not nm or band == "low":
            continue
        # pi_matrix forces pi to 0 where the vehicle has no access (passability.py:33).
        # That is right for routing — an edge you may not use is not an edge you can be
        # sent down — but it makes pi ambiguous as a *ranking* key here, because it
        # collapses "deep water" and "no motorbikes allowed" onto the same 0. Ranking on
        # it puts a dry pedestrian overpass above a street under half a metre of water.
        # This list answers "where is the flooding worst", so the legal restriction is
        # filtered out before ranking and the depth ordering is left to speak about water.
        # The band counts above are deliberately NOT filtered: they describe the whole
        # network as the router sees it.
        if not access[e]:
            no_access_streets.add(nm)
            continue
        pi = float(st["pi"][e])
        cur = by_street.get(nm)
        if cur is None or pi < cur["pi_passable"]:
            by_street[nm] = {
                "street": nm, "risk_band": band, "risk_band_vi": BAND_VI[band],
                "pi_passable": round(pi, 3),
                "depth_p50_cm": round(float(st["p50_cm"][e]), 1),
                **_evidence(st["age_s"][e]),
            }
    worst = sorted(by_street.values(), key=lambda d: d["pi_passable"])[:top_n]
    return {
        "tick": tick, "minutes_from_event_start": tick * sc.tick_s // 60,
        "vehicle": vehicle,
        "segments_by_band": dict(counts),
        "n_named_streets_at_risk": len(by_street),
        "worst_streets": worst,
        # Named streets held out of the ranking because this vehicle may not use them at
        # all (footbridges, motorway links). Reported rather than dropped silently, so the
        # list can be read as complete for what it claims to cover.
        "n_streets_excluded_no_access": len(no_access_streets - set(by_street)),
        "ranking_note": ("worst_streets xếp theo mức ngập trên các đoạn phương tiện này "
                         "được phép đi; đoạn cấm phương tiện không nằm trong danh sách."),
        "units": {"depth_p50_cm": "centimetres",
                  "evidence_age_s": "seconds since last evidence, null if never observed",
                  "pi_passable": "probability 0-1 that the segment is passable"},
        "evidence_class": "simulated",
        "is_synthetic": True,
    }
