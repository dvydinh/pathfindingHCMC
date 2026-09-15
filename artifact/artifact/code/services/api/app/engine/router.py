"""Time-dependent risk-aware routing (proposal C5).

Dijkstra over nodes with arrival-tick-dependent edge costs:
    cost(e, t_arr) = tt + l1*tt*CVaR90(unsafe) + l2*tt*width_norm (+ stale term)
subject to a union-bound chance constraint  sum_e p_unsafe(e, t_arr) <= alpha_v.
Consumer profiles hard-block edges beyond the envelope (band avoid) and closures —
the safety policy: unsafe edges are not "expensive", they are not offered.
If no path satisfies the constraint -> no_safe_route + wait-and-depart-later scan.
"""
from __future__ import annotations
import heapq, math
import numpy as np
from .state import Scenario, STALE_S
from .passability import member_passability, pi_matrix, ENVELOPE

ALPHA = {"motorbike": 0.05, "e_2w": 0.05, "car": 0.05, "response": 0.20}
# Per-edge unsafety below this floor is envelope-sigmoid tail noise (depth far below
# the caution line), not meaningful risk signal; excluding it keeps the union bound
# about genuinely risky edges instead of path length.
P_NOISE_FLOOR = 0.01
L1, L2 = 6.0, 1.2
AVOID_PI = 0.55
RETRY_MULT = [1.0, 4.0, 16.0]
WAIT_OFFSETS = [3, 6, 12, 18]           # ticks (15/30/60/90 min)

def _tick_layer(sc: Scenario, vehicle: str, tick: int) -> dict:
    """Vectorised per-tick cost ingredients, cached on the scenario."""
    key = ("layer", vehicle, tick, sc.version)
    if key in sc._pi_cache:
        return sc._pi_cache[key]
    tick = min(tick, sc.T - 1)
    W = sc.weights(tick)
    h = sc.ens[tick].astype(np.float64)
    unsafe = 1.0 - member_passability(h, vehicle)          # (E, N)
    p_unsafe = (unsafe * W).sum(axis=1)
    p_constraint = np.where(p_unsafe > P_NOISE_FLOOR, p_unsafe, 0.0)
    # CVaR_90: expected unsafety in the worst 10% of members (weighted)
    thr = np.quantile(h, 0.9, axis=1, keepdims=True)
    tailmask = (h >= thr)
    cvar = (unsafe * W * tailmask).sum(axis=1) / np.maximum((W * tailmask).sum(axis=1), 1e-9)
    p10, p50, p90 = sc.quantiles(tick)
    width_norm = np.clip((p90 - p10) / 20.0, 0, 1)
    pi = pi_matrix(sc, vehicle, tick)
    blocked = (pi < AVOID_PI) | ~sc.g.access[vehicle]
    for e in sc.closures:
        blocked[e] = True
        p_unsafe[e] = 1.0
        p_constraint[e] = 1.0
    layer = {"p_unsafe": p_unsafe, "p_constraint": p_constraint, "cvar": cvar,
             "width": width_norm, "blocked": blocked}
    sc._pi_cache[key] = layer
    return layer

def _snap_index(sc: Scenario):
    """Snap targets: nodes in the largest STRONGLY-connected motorbike-accessible core
    (forward ∩ backward BFS from a well-connected hub) — guarantees any snapped
    origin/destination pair is mutually routable in the dry graph."""
    key = "snap_idx"
    if key not in sc._pi_cache:
        from collections import deque
        g = sc.g
        acc = g.access["motorbike"]
        in_edges: dict[int, list[int]] = {}
        for i in range(g.n):
            if acc[i]:
                in_edges.setdefault(int(g.v[i]), []).append(i)
        hub = max(g.out_edges, key=lambda n: len(g.out_edges[n]))
        def bfs(start: int, forward: bool) -> set[int]:
            seen = {start}; q = deque([start])
            while q:
                n = q.popleft()
                if forward:
                    nxt = (int(g.v[e]) for e in g.out_edges.get(n, []) if acc[e])
                else:
                    nxt = (int(g.u[e]) for e in in_edges.get(n, []))
                for v in nxt:
                    if v not in seen:
                        seen.add(v); q.append(v)
            return seen
        core = bfs(int(hub), True) & bfs(int(hub), False)
        nodes, xs, ys = [], [], []
        for n in core:
            edges = g.out_edges.get(n, [])
            if edges:
                x, y = g.coords[edges[0]][0]
                nodes.append(int(n)); xs.append(x); ys.append(y)
        sc._pi_cache[key] = (np.array(nodes), np.array(xs), np.array(ys))
    return sc._pi_cache[key]

def snap(sc: Scenario, lon: float, lat: float) -> int:
    nodes, xs, ys = _snap_index(sc)
    return int(nodes[np.argmin((xs - lon) ** 2 + (ys - lat) ** 2)])

# Nearest-neighbour snapping has no natural failure: any coordinate on earth returns
# *some* node, so a wrong point yields a confident route between places nobody asked
# about. Callers that accept coordinates from outside the UI (the assistant) must use
# snap_checked and refuse beyond this radius rather than silently relocate the user.
SNAP_MAX_M = 300.0

def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))

def snap_checked(sc: Scenario, lon: float, lat: float) -> tuple[int | None, float]:
    """(node, distance_m) — node is None when the nearest node is farther than SNAP_MAX_M."""
    nodes, xs, ys = _snap_index(sc)
    i = int(np.argmin((xs - lon) ** 2 + (ys - lat) ** 2))
    d = _haversine_m(lon, lat, float(xs[i]), float(ys[i]))
    return (int(nodes[i]) if d <= SNAP_MAX_M else None), d

VMAX_MS = 80 / 3.6      # A* heuristic speed bound (fastest road class)

def _node_coords(sc: Scenario) -> dict[int, tuple[float, float]]:
    key = "node_xy"
    if key not in sc._pi_cache:
        g = sc.g
        xy: dict[int, tuple[float, float]] = {}
        for i in range(g.n):
            xy[int(g.u[i])] = tuple(g.coords[i][0])
            xy[int(g.v[i])] = tuple(g.coords[i][-1])
        sc._pi_cache[key] = xy
    return sc._pi_cache[key]

def _fast_layer(sc: Scenario, vehicle: str, tick: int, risk_mult: float,
                flood_aware: bool) -> dict:
    """Search-optimised per-tick layer: plain lists/sets so the A* inner loop does
    zero numpy scalar boxing."""
    key = ("fast", vehicle, tick, round(risk_mult, 3), flood_aware, sc.version)
    if key in sc._pi_cache:
        return sc._pi_cache[key]
    layer = _tick_layer(sc, vehicle, tick)
    g = sc.g
    tt = g.travel_time_s()
    if flood_aware:
        cost = tt * (1.0 + L1 * risk_mult * layer["cvar"] + L2 * layer["width"])
        blocked = set(np.flatnonzero(layer["blocked"]).tolist())
    else:
        cost = tt.copy()
        blocked = set(np.flatnonzero(~g.access[vehicle]).tolist()) | set(sc.closures)
    fast = {"cost": cost.tolist(), "pcon": layer["p_constraint"].tolist(),
            "tt": tt.tolist(), "blocked": blocked}
    while len(sc._pi_cache) > 900:
        del sc._pi_cache[next(iter(sc._pi_cache))]
    sc._pi_cache[key] = fast
    return fast

def _search(sc: Scenario, vehicle: str, src: int, dst: int, depart_tick: int,
            risk_mult: float, flood_aware: bool) -> dict | None:
    g = sc.g
    tt = g.travel_time_s()
    INF = math.inf
    xy = _node_coords(sc)
    dx, dy = xy[dst]
    coslat = math.cos(math.radians(dy))
    def h(node: int) -> float:
        # admissible: straight-line distance at the fastest possible speed;
        # risk/uncertainty penalties are nonnegative additions on top of time.
        x, y = xy[node]
        dist_m = 111_320.0 * math.hypot((x - dx) * coslat, y - dy)
        return dist_m / VMAX_MS
    dist: dict[int, float] = {src: 0.0}
    risk_acc: dict[int, float] = {src: 0.0}
    prev_edge: dict[int, int] = {}
    pq = [(h(src), src)]
    seen = set()
    while pq:
        _, node = heapq.heappop(pq)
        if node in seen:
            continue
        seen.add(node)
        d = dist[node]
        if node == dst:
            break
        arr_tick = min(depart_tick + int(d // sc.tick_s), sc.T - 1)
        fast = _fast_layer(sc, vehicle, arr_tick, risk_mult, flood_aware)
        cost, pcon, blocked = fast["cost"], fast["pcon"], fast["blocked"]
        r_here = risk_acc.get(node, 0.0)
        for e in g.out_edges.get(node, []):
            if e in blocked:
                continue
            nd = d + cost[e]
            v2 = g.v_int[e]
            if nd < dist.get(v2, INF):
                dist[v2] = nd
                risk_acc[v2] = r_here + pcon[e]
                prev_edge[v2] = e
                heapq.heappush(pq, (nd + h(v2), v2))
    if dst not in prev_edge and dst != src:
        return None
    # reconstruct
    edges, node = [], dst
    while node != src:
        e = prev_edge[node]
        edges.append(e)
        node = int(sc.g.u[e])
    edges.reverse()
    # true metrics along the path (independent of the search's penalties)
    t_cum, exp_s, max_p, sum_p = 0.0, 0.0, 0.0, 0.0
    ages = []
    for e in edges:
        arr_tick = min(depart_tick + int(t_cum // sc.tick_s), sc.T - 1)
        layer = _tick_layer(sc, vehicle, arr_tick)
        p = float(layer["p_unsafe"][e])
        te = float(tt[e])
        t_cum += te
        exp_s += te * p
        max_p = max(max_p, p)
        sum_p += float(layer["p_constraint"][e])
    return {"edges": edges, "travel_time_s": t_cum, "risk_exposure_s": exp_s,
            "max_edge_risk": max_p, "sum_p_unsafe": sum_p}

def _merge_legs(legs: list[dict]) -> dict:
    """Concatenate per-leg results into one trip; risk sums, times add."""
    return {
        "edges": [e for leg in legs for e in leg["edges"]],
        "travel_time_s": sum(l["travel_time_s"] for l in legs),
        "risk_exposure_s": sum(l["risk_exposure_s"] for l in legs),
        "max_edge_risk": max((l["max_edge_risk"] for l in legs), default=0.0),
        "sum_p_unsafe": sum(l["sum_p_unsafe"] for l in legs),
        "leg_times_s": [round(l["travel_time_s"], 1) for l in legs],
    }

def _chain(sc: Scenario, vehicle: str, nodes: list[int], depart_tick: int,
           risk_mult: float, flood_aware: bool) -> dict | None:
    """Route through every node in order. Each leg departs at the ARRIVAL tick of the
    previous leg — the multi-stop trip sees the storm as it will be, not as it is."""
    legs, t_cum = [], 0.0
    for a, b in zip(nodes, nodes[1:]):
        tick = min(depart_tick + int(t_cum // sc.tick_s), sc.T - 1)
        leg = _search(sc, vehicle, a, b, tick, risk_mult, flood_aware)
        if leg is None:
            return None
        legs.append(leg)
        t_cum += leg["travel_time_s"]
    return _merge_legs(legs)

def route(sc: Scenario, vehicle: str, o: tuple, d: tuple, depart_tick: int,
          include_conservative: bool = False, waypoints: list | None = None) -> dict:
    pts = [o] + [tuple(w) for w in (waypoints or [])] + [d]
    nodes = [snap(sc, *p) for p in pts]
    alpha = ALPHA[vehicle]
    dry = _chain(sc, vehicle, nodes, depart_tick, 0.0, flood_aware=False)

    rec, connected = None, True
    for m in RETRY_MULT:
        cand = _chain(sc, vehicle, nodes, depart_tick, m, flood_aware=True)
        if cand is None:
            # blocked-set is independent of the risk multiplier: no path now means
            # no path at ANY multiplier -> skip retries and conservative search
            connected = False
            break
        if cand["sum_p_unsafe"] <= alpha:
            rec = cand
            break
    cons = (_chain(sc, vehicle, nodes, depart_tick, RETRY_MULT[-1] * 2, flood_aware=True)
            if connected and include_conservative else None)

    wait = None
    if rec is None:
        for off in WAIT_OFFSETS[1:3]:            # 30/60 min: two probes keep p95 in budget
            t2 = depart_tick + off
            if t2 >= sc.T:
                break
            cand = _chain(sc, vehicle, nodes, t2, RETRY_MULT[1], flood_aware=True)
            if cand and cand["sum_p_unsafe"] <= alpha:
                wait = {"depart_tick": t2,
                        "reason": "risk subsides; a compliant route exists later"}
                break
    sc.recent_routes.append(set((rec or dry or {"edges": []})["edges"]))
    return {"nodes": nodes, "n_legs": len(nodes) - 1, "dry": dry, "recommended": rec,
            "conservative": cons, "wait": wait, "alpha": alpha,
            # This search is deliberately partial to protect the interactive p95. A null
            # wait therefore means "none found at these offsets", never "none exists" —
            # callers that present it as the latter would be overstating the result.
            "wait_probed_offsets_min": [o * sc.tick_s // 60 for o in WAIT_OFFSETS[1:3]],
            "wait_search_is_partial": True}

# Departure-window scan. route() deliberately probes only two wait offsets to protect the
# interactive p95, which means a "no safe route" answer there can hide a compliant
# departure 15 minutes away. This does the thorough search instead, coarse-to-fine so the
# cost stays near a dozen A* runs rather than one per tick.
SCAN_STEP = 3                    # coarse probe every 15 minutes
SCAN_DEFAULT_TICKS = 24          # 2 hours ahead unless the caller says otherwise


def _compliant(sc: Scenario, vehicle: str, nodes: list, tick: int):
    """One flood-aware attempt at a tick; returns the leg result if it clears alpha."""
    cand = _chain(sc, vehicle, nodes, tick, RETRY_MULT[1], flood_aware=True)
    if cand is None:
        return None, False
    return cand, cand["sum_p_unsafe"] <= ALPHA[vehicle]


def departure_window(sc: Scenario, vehicle: str, o: tuple, d: tuple, from_tick: int,
                     within_ticks: int = SCAN_DEFAULT_TICKS,
                     waypoints: list | None = None) -> dict:
    """Scan departures from `from_tick` forward and report when the trip clears.

    Returns the earliest compliant departure, the lowest-exposure one, and a coarse
    risk-versus-time profile. Everything is computed here; a caller may narrate it but
    must not extrapolate between probes, so the probed ticks are reported explicitly.
    """
    pts = [o] + [tuple(w) for w in (waypoints or [])] + [d]
    nodes = [snap(sc, *p) for p in pts]
    from_tick = max(0, min(int(from_tick), sc.T - 1))
    last = min(sc.T - 1, from_tick + max(1, int(within_ticks)))

    profile, probed = [], []
    first_ok = None
    for t in range(from_tick, last + 1, SCAN_STEP):
        cand, ok = _compliant(sc, vehicle, nodes, t)
        probed.append(t)
        profile.append({
            "tick": t, "in_minutes": (t - from_tick) * sc.tick_s // 60,
            "compliant": ok,
            "travel_min": round(cand["travel_time_s"] / 60, 1) if cand else None,
            "risk_exposure_s": round(cand["risk_exposure_s"], 1) if cand else None,
        })
        if ok and first_ok is None:
            first_ok = t
            break                                   # refine below, then stop scanning

    earliest = None
    if first_ok is not None:
        # Walk back tick by tick: the true crossing lies inside the coarse step.
        best_t, best = first_ok, None
        for t in range(first_ok - 1, max(from_tick, first_ok - SCAN_STEP) - 1, -1):
            cand, ok = _compliant(sc, vehicle, nodes, t)
            probed.append(t)
            if not ok:
                break
            best_t, best = t, cand
        if best is None:
            best, _ = _compliant(sc, vehicle, nodes, best_t)
        earliest = {
            "depart_tick": best_t,
            "in_minutes": (best_t - from_tick) * sc.tick_s // 60,
            "travel_min": round(best["travel_time_s"] / 60, 1),
            "risk_exposure_s": round(best["risk_exposure_s"], 1),
        }

    compliant_probes = [p for p in profile if p["compliant"]]
    lowest = min(compliant_probes,
                 key=lambda p: (p["risk_exposure_s"], p["travel_min"])) \
        if compliant_probes else None
    return {
        "from_tick": from_tick, "searched_to_tick": last,
        "window_minutes": (last - from_tick) * sc.tick_s // 60,
        "step_minutes": SCAN_STEP * sc.tick_s // 60,
        "earliest_compliant": earliest,
        "lowest_exposure_probe": lowest,
        "profile": profile,
        "probed_ticks": sorted(set(probed)),
        "found": earliest is not None,
        "alpha": ALPHA[vehicle],
    }


def geometry(sc: Scenario, edges: list[int]) -> dict:
    coords = []
    for e in edges:
        cs = sc.g.coords[e]
        coords.extend(cs if not coords else cs[1:])
    return {"type": "LineString", "coordinates": coords}
