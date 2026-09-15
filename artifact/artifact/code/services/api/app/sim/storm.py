"""Precompute the scenario: truth run + forecast ensemble + simulated feeds.
Content-addressed output (G2.1: same spec+seed -> identical bytes)."""
import hashlib, json, os, sys
import numpy as np
import yaml
from ..deps import DATA, scenes, default_scene
from ..engine import graph, hydro

def spec_for(scene: str) -> tuple[dict, str]:
    name = scenes()[scene]["scenario"]
    p = os.path.join(os.path.dirname(__file__), "scenarios", f"{name}.yaml")
    raw = open(p, "rb").read()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()[:12]

def make_feeds(g, spec: dict, truth: np.ndarray, rng: np.random.Generator) -> list[dict]:
    """Simulated gauge/camera observations drawn from the truth run through
    source noise models. All records is_synthetic=true (I6)."""
    T = spec["ticks"]
    order = np.argsort(-g.sink)
    obs = []
    fs = spec["feeds"]
    gauges = order[: fs["gauges"]["count"]]
    cams = order[fs["gauges"]["count"]: fs["gauges"]["count"] + fs["cameras"]["count"]]
    for fi, e in enumerate(gauges):
        for t in range(0, T, fs["gauges"]["every_ticks"]):
            val = float(truth[t, e] + rng.normal(0, fs["gauges"]["noise_cm"]))
            obs.append({"feed_id": f"gauge-{fi}", "source_class": "gauge", "edge": int(e),
                        "tick": t, "depth_cm": round(max(val, 0.0), 1),
                        "noise_cm": fs["gauges"]["noise_cm"]})
    for fi, e in enumerate(cams):
        for t in range(0, T, fs["cameras"]["every_ticks"]):
            val = float(truth[t, e] + rng.normal(0, fs["cameras"]["noise_cm"]))
            obs.append({"feed_id": f"camera-{fi}", "source_class": "camera", "edge": int(e),
                        "tick": t, "depth_cm": round(max(val, 0.0), 1),
                        "noise_cm": fs["cameras"]["noise_cm"]})
    return obs

def main() -> None:
    scene = os.environ.get("SCENE", default_scene())
    g = graph.load(scene)
    spec, spec_hash = spec_for(scene)
    print(f"[storm] scene={scene} spec={spec['name']}@{spec_hash} edges={g.n}")

    truth_arr, tguards = hydro.run_ensemble(g, spec, seed_offset=777, n_members=1)
    truth = truth_arr[:, :, 0]                       # (T, E)
    ens, guards = hydro.run_ensemble(g, spec)        # (T, E, N)
    rng = np.random.default_rng(spec["seed"] + 99)
    feeds = make_feeds(g, spec, truth, rng)

    outdir = DATA / "scenarios"
    outdir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(outdir / f"{scene}_{spec_hash}.npz",
                        ensemble=ens, truth=truth.astype(np.float32))
    # uncompressed sidecars: near-instant mmap load at runtime
    np.save(outdir / f"{scene}_{spec_hash}_ens.npy", ens)
    np.save(outdir / f"{scene}_{spec_hash}_truth.npy", truth.astype(np.float32))
    meta = {
        "scene": scene, "scenario": spec["name"], "spec_hash": spec_hash,
        "seed": spec["seed"], "ticks": spec["ticks"], "tick_minutes": spec["tick_minutes"],
        "ensemble": spec["ensemble"], "feeds": feeds,
        "guards": guards.as_dict(), "truth_guards": tguards.as_dict(),
        "is_synthetic": True,
    }
    (outdir / f"{scene}_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    # quantile summary (parquet per WORKFLOW post-requirement)
    import pyarrow as pa, pyarrow.parquet as pq
    T, E, N = ens.shape
    q = np.percentile(ens, [10, 50, 90], axis=2)     # (3, T, E)
    tt, ee = np.meshgrid(np.arange(T), np.arange(E), indexing="ij")
    table = pa.table({
        "tick": tt.ravel().astype(np.int32), "edge_idx": ee.ravel().astype(np.int32),
        "p10": q[0].ravel(), "p50": q[1].ravel(), "p90": q[2].ravel(),
        "is_synthetic": np.ones(T * E, dtype=bool),
    })
    pq.write_table(table, outdir / f"{scene}_{spec_hash}_quantiles.parquet")

    wet = (truth.max(axis=0) > 5).sum()
    print(f"[ok] ensemble {ens.shape} truth-wet-edges(>5cm)={wet} "
          f"guards={guards.as_dict()} -> {outdir}")

if __name__ == "__main__":
    main()
