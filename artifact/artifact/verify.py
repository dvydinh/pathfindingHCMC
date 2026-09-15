#!/usr/bin/env python3
"""Check the artifact's claims against the running code.

Every row below is a number stated somewhere in the paper, the README, or the docs. The
point of this script is that a reviewer can disagree with it: each claim names where it
comes from and what it expects, so a mismatch is visible rather than arguable.

Usage:
    DATA_DIR=./data CONFIG_DIR=../config PYTHONPATH=../services/api python verify.py
    (or simply: bash reproduce.sh, which sets these for you)
"""
from __future__ import annotations
import json
import os
import sys
import traceback

RESULTS: list[tuple[str, str, str, bool]] = []


def check(name: str, expected, got, ok: bool | None = None) -> None:
    if ok is None:
        ok = expected == got
    RESULTS.append((name, str(expected), str(got), bool(ok)))


def approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def main() -> int:
    from app.engine import (charging, environment, gazetteer, router as R, state)
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    sc = state.get("thuduc")

    # ---- graph -------------------------------------------------------------
    check("graph: directed edges (Thu Duc)", 25809, sc.g.n)
    named = sum(1 for n in sc.g.name if n)
    check("graph: edges with an OSM street name", 12819, named)

    # ---- gazetteer ---------------------------------------------------------
    gz = gazetteer.load("thuduc")
    check("gazetteer: streets", 1368, len(gz["streets"]))
    check("gazetteer: landmarks", 517, len(gz["landmarks"]))
    all_osm = all(e["source"] == "osm" for e in gz["streets"] + gz["landmarks"])
    check("gazetteer: every entry sourced from OSM (never invented)", True, all_osm)

    # ---- refusal behaviour -------------------------------------------------
    r = gazetteer.resolve("thuduc", "chợ Bến Thành")
    check("refusal: out-of-area market is not_found", "not_found", r["status"])
    check("refusal: ...with no usable candidate offered", 0, len(r["candidates"]))
    check("disambiguation: 'đường Tam Bình' -> a street", "street",
          gazetteer.resolve("thuduc", "đường Tam Bình")["candidates"][0]["kind"])
    check("disambiguation: 'phường Tam Bình' -> a suburb", "suburb",
          gazetteer.resolve("thuduc", "phường Tam Bình")["candidates"][0]["kind"])
    vng = gazetteer.resolve("thuduc", "đường Võ Nguyên Giáp")["candidates"][0]
    check("merge: head-noun variant resolves to the arterial, not the 239 m stub",
          True, vng["name"] == "Võ Nguyên Giáp" and vng["n_edges"] > 100)

    # ---- grounding invariants ---------------------------------------------
    from app.routers import assistant as A
    # No credential is set or needed: building the tool set only exercises the schema
    # decorator, never a client. This script must run in a bundle that ships no keys.
    tools = A._make_tools("thuduc", {})
    coord_params = set()
    for t in tools:
        d = t.to_dict()
        coord_params |= set(d["input_schema"].get("properties", {})) & {
            "lon", "lat", "o_lon", "o_lat", "d_lon", "d_lat"}
    check("I8: no assistant tool accepts a coordinate", set(), coord_params)
    check("assistant: read-only tool count", 8, len(tools))
    node, dist = R.snap_checked(sc, 105.85, 21.03)          # Hoan Kiem, Hanoi
    check("bounded snap: a Hanoi coordinate is refused, not relocated", True,
          node is None and dist > 1_000_000)

    # ---- sensor coverage ---------------------------------------------------
    cov = client.get("/v1/ops/sensor-coverage").json()
    check("sensing: sensors in the scenario", 38, cov["n_sensors"])
    check("sensing: edges reached by any sensor", 161, cov["n_edges_covered"])
    check("sensing: network length observed (%)", 0.8, cov["pct_length_covered"],
          approx(cov["pct_length_covered"], 0.8, 0.05))

    # ---- OSM attribute completeness ---------------------------------------
    counts: dict[float, int] = {}
    for q in sc.g.quality:
        counts[round(float(q), 2)] = counts.get(round(float(q), 2), 0) + 1
    check("completeness: distinct data_quality values", 3, len(counts))
    check("completeness: edges missing both width and surface", 18542, counts.get(0.5))
    check("completeness: edges with one of the two", 7263, counts.get(0.75))
    check("completeness: edges with both", 4, counts.get(1.0))

    # ---- rainfall ----------------------------------------------------------
    wx = client.get("/v1/weather?at=0").json()
    curve, accum = wx["rain_curve"], wx["rain_accum_curve_mm"]
    check("rain: event total (mm)", 130.0, wx["rain_accum_total_mm"],
          approx(wx["rain_accum_total_mm"], 130.0, 0.5))
    check("rain: accumulation is monotone", True,
          all(b >= a for a, b in zip(accum, accum[1:])))
    integral, drift = 0.0, 0.0
    for i, mm_h in enumerate(curve):
        integral += mm_h * (5 / 60)
        drift = max(drift, abs(accum[i] - integral))
    check("rain: accumulation equals the integral of the displayed curve", True,
          drift < 0.15)

    # ---- ambient layer (real data) ----------------------------------------
    env = client.get("/v1/environment?hour=0").json()
    check("ambient: labelled observed, not simulated", "observed", env["evidence_class"])
    check("ambient: does not feed routing", False, env["affects_routing"])
    check("ambient: distinct source cells over a 6.6 km scene", 4, env["n_source_cells"])
    check("ambient: source cell spacing (km)", 7.8, env["source_cell_span_km"],
          approx(env["source_cell_span_km"], 7.8, 0.3))

    # ---- charging ----------------------------------------------------------
    ch = client.get("/v1/charging?at=24&vehicle=e_2w").json()
    check("charging: stations mapped inside the demo bbox", 0, ch["n_in_scene"])
    check("charging: reported as a coverage gap, not as absence", True,
          ch["no_station_mapped_in_scene"] and bool(ch["coverage_note"]))
    nearest = ch["nearest_outside_scene"][0]["km_from_scene_centre"]
    check("charging: nearest real station (km from scene centre)", 7.5, nearest,
          approx(nearest, 7.5, 0.2))
    check("charging: location provenance kept apart from reachability", True,
          ch["location_evidence_class"] == "real geometry"
          and ch["access_evidence_class"] == "simulated")

    # ---- report ------------------------------------------------------------
    width = max(len(r[0]) for r in RESULTS)
    print(f"\n{'CLAIM'.ljust(width)}  {'EXPECTED':>12}  {'GOT':>12}   ")
    print("-" * (width + 34))
    for name, exp, got, ok in RESULTS:
        mark = "PASS" if ok else "FAIL"
        print(f"{name.ljust(width)}  {exp:>12}  {got:>12}  {mark}")
    failed = [r for r in RESULTS if not r[3]]
    print("-" * (width + 34))
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} claims verified")
    if failed:
        print("\nFAILED:")
        for name, exp, got, _ in failed:
            print(f"  {name}: expected {exp}, got {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print("\nverify.py could not run. Most likely the scenario is not built yet:")
        print("  see README.md section 'Reproducing from scratch'")
        sys.exit(2)
