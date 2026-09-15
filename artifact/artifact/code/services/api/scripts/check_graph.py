"""Gate G1.1/G1.2 checks: edge count band, elevation nulls, sink_score non-degenerate."""
import json, sys
import numpy as np
from common import DERIVED, scene_name

scene = scene_name()
edges = json.loads((DERIVED / f"{scene}_edges.json").read_text(encoding="utf-8"))
n = len(edges)
sink = np.array([e.get("sink_score", np.nan) for e in edges])
z = np.array([e.get("z_min", np.nan) for e in edges])
nulls = float(np.mean(np.isnan(z))) * 100
ok = True
def check(name, cond, detail):
    global ok
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")
    ok = ok and cond
print(f"check_graph — scene {scene}")
check("G1.1 edge count", 1500 <= n <= 30000, f"{n} directed edges (band widened per DECISIONS 005)")
check("G1.2 null elevation", nulls < 2.0, f"{nulls:.2f}% null")
check("G1.2 sink_score non-degenerate", np.nanstd(sink) > 0.02, f"std={np.nanstd(sink):.3f}")
sys.exit(0 if ok else 1)
