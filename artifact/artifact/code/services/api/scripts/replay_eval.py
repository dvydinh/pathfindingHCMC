"""M7 routing benchmark (G7.1/G7.2): matched OD pairs, evaluated against the OSSE
truth run. Baselines: B0 dry router, B6 official-only. No cherry-picking: every
sampled OD pair is reported, including ones where risk-aware loses time.
Exposure ground truth = seconds spent on edges whose TRUE depth exceeds the
vehicle refuse envelope at traversal time."""
import json, sys, time
import numpy as np
sys.path.insert(0, "/srv")
from app.engine import state, router
from app.engine.passability import ENVELOPE
from common import DATA

N_OD = 60
DEPART_TICKS = [14, 18, 22, 26]
VEHICLE = "motorbike"
SEED = 4242

def true_exposure(sc, edges, depart_tick, vehicle):
    """Seconds on edges whose TRUE depth exceeds the refuse envelope when traversed."""
    refuse = ENVELOPE[vehicle][1]
    tt = sc.g.travel_time_s()
    t_cum, exp = 0.0, 0.0
    for e in edges:
        tick = min(depart_tick + int(t_cum // sc.tick_s), sc.T - 1)
        if sc.truth[tick, e] > refuse:
            exp += float(tt[e])
        t_cum += float(tt[e])
    return exp, t_cum

def official_only_route(sc, o, d, depart_tick):
    """B6: knows closures but no model. Same as dry search (closures blocked)."""
    return router._search(sc, VEHICLE, router.snap(sc, *o), router.snap(sc, *d),
                          depart_tick, 0.0, flood_aware=False)

def main():
    sc = state.get("thuduc")
    rng = np.random.default_rng(SEED)
    g = sc.g
    lon = np.array([c[0][0] for c in g.coords]); lat = np.array([c[0][1] for c in g.coords])
    rows = []
    t0 = time.time()
    for k in range(N_OD):
        i, j = rng.integers(0, g.n, 2)
        if abs(lon[i] - lon[j]) + abs(lat[i] - lat[j]) < 0.015:
            continue                      # skip trivial trips
        o, d = (float(lon[i]), float(lat[i])), (float(lon[j]), float(lat[j]))
        dt = int(rng.choice(DEPART_TICKS))
        res = router.route(sc, VEHICLE, o, d, dt)
        if not res["dry"]:
            continue
        row = {"od": k, "depart_tick": dt}
        for name, r in (("dry", res["dry"]),
                        ("official", official_only_route(sc, o, d, dt)),
                        ("risk_aware", res["recommended"])):
            if r is None:
                row[name] = None
                continue
            exp, tt = true_exposure(sc, r["edges"], dt, VEHICLE)
            row[name] = {"travel_s": round(tt, 1), "true_unsafe_exposure_s": round(exp, 1)}
        row["no_safe_route"] = res["recommended"] is None
        rows.append(row)
    # aggregate with a simple OD-level bootstrap (single simulated storm —
    # honest label: this is NOT a storm-block CI, one event only)
    def agg(name):
        vals = [(r[name]["true_unsafe_exposure_s"], r[name]["travel_s"])
                for r in rows if r.get(name)]
        if not vals:
            return None
        exp = np.array([v[0] for v in vals]); tt = np.array([v[1] for v in vals])
        boot = np.random.default_rng(1).choice(len(vals), (2000, len(vals)))
        bexp = exp[boot].mean(axis=1)
        return {"n": len(vals),
                "mean_unsafe_exposure_s": round(float(exp.mean()), 1),
                "exposure_ci95": [round(float(np.percentile(bexp, 2.5)), 1),
                                   round(float(np.percentile(bexp, 97.5)), 1)],
                "mean_travel_s": round(float(tt.mean()), 1),
                "pct_od_with_exposure": round(float((exp > 0).mean() * 100), 1)}
    # matched comparison: only OD pairs where BOTH dry and risk_aware produced a route
    matched = [r for r in rows if r.get("dry") and r.get("risk_aware")]
    matched_cmp = None
    if matched:
        d_exp = np.array([r["dry"]["true_unsafe_exposure_s"] for r in matched])
        a_exp = np.array([r["risk_aware"]["true_unsafe_exposure_s"] for r in matched])
        d_tt = np.array([r["dry"]["travel_s"] for r in matched])
        a_tt = np.array([r["risk_aware"]["travel_s"] for r in matched])
        matched_cmp = {
            "n": len(matched),
            "dry_mean_exposure_s": round(float(d_exp.mean()), 1),
            "risk_aware_mean_exposure_s": round(float(a_exp.mean()), 1),
            "mean_added_time_s": round(float((a_tt - d_tt).mean()), 1),
            "note": "paired on identical OD+depart; the honest apples-to-apples cut",
        }
    out = {
        "design": "OSSE replay, single simulated compound event; OD-level bootstrap CI "
                  "(NOT a storm-block CI — one storm only). Exposure measured against the "
                  "designated truth run.",
        "matched_comparison": matched_cmp,
        "refusal_note": "no_safe_route responses are a safety outcome, not missing data: "
                        "at storm peak many cross-town trips genuinely traverse flooded "
                        "corridors and the router advises waiting.",
        "vehicle": VEHICLE, "n_od_sampled": len(rows),
        "methods": {"dry_B0": agg("dry"), "official_only_B6": agg("official"),
                    "risk_aware": agg("risk_aware")},
        "no_safe_route_count": sum(1 for r in rows if r["no_safe_route"]),
        "runtime_s": round(time.time() - t0, 1),
        "per_od": rows,
        "is_synthetic": True,
    }
    outdir = DATA / "eval"; outdir.mkdir(exist_ok=True)
    (outdir / "replay_metrics.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    m = out["methods"]
    print(f"[ok] {len(rows)} OD pairs")
    for k in ("dry_B0", "official_only_B6", "risk_aware"):
        print(f"  {k}: {m[k]}")

if __name__ == "__main__":
    main()
