"""Truth-only quick run to calibrate forcing constants (dev tool, not a gate)."""
import numpy as np, yaml, os, sys
sys.path.insert(0, "/srv")
from app.engine import graph, hydro
from app.sim.storm import spec_for

scene = os.environ.get("SCENE", "thuduc")
g = graph.load(scene)
spec, h = spec_for(scene)
truth, guards = hydro.run_ensemble(g, spec, seed_offset=777, n_members=1)
t = truth[:, :, 0]
peak = t.max(axis=0)
wet = peak > 5
import numpy as np
corr = np.corrcoef(np.argsort(np.argsort(peak)), np.argsort(np.argsort(g.sink)))[0, 1]
print(f"wet>5cm: {wet.sum()} ({100*wet.mean():.1f}%)  peak p50/p90/p99/max: "
      f"{np.percentile(peak,50):.1f}/{np.percentile(peak,90):.1f}/"
      f"{np.percentile(peak,99):.1f}/{peak.max():.1f} cm")
print(f"sink-rank corr: {corr:.3f}   guards: {guards.as_dict()}")
top = np.argsort(-g.sink)[:100]
print(f"top-100-sink edges peak median: {np.median(peak[top]):.1f} cm")
