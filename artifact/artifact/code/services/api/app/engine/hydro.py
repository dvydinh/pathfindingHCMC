"""Physics transition (proposal C2 prior term), vectorised over edges and ensemble members.

    h+ = [ h + alpha*r + q_in - q_out - kappa*h ]_+   (learned residual f_theta: stretch only)

Runtime guard counters implement the L_mass / L_flow / L_temporal disciplines as
assertions + telemetry rather than training losses (PLAN.md §4.1).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from .graph import Graph

@dataclass
class Guards:
    clamp_count: int = 0
    max_jump_cm: float = 0.0
    jump_warns: int = 0

    def as_dict(self) -> dict:
        return {"negative_depth_clamps": self.clamp_count,
                "max_jump_cm": round(self.max_jump_cm, 1),
                "temporal_jump_warnings": self.jump_warns}

def build_flow_index(g: Graph) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(src_edge, dst_edge, share) arrays for downhill routing. Uphill flow is
    impossible by construction (downhill lists only) — the L_flow guarantee."""
    src, dst, share = [], [], []
    for i, succs in enumerate(g.downhill):
        succs = [j for j in succs if j is not None]
        if not succs:
            continue
        w = 1.0 / len(succs)
        for j in succs:
            src.append(i); dst.append(j); share.append(w)
    return (np.array(src, dtype=np.int32), np.array(dst, dtype=np.int32),
            np.array(share, dtype=np.float32))

def step(h: np.ndarray, g: Graph, phys: dict, rain_mm_h: float, tide_m: float,
         rain_mult: np.ndarray, kappa_mult: np.ndarray, tide_off: np.ndarray,
         flow_idx: tuple, guards: Guards) -> np.ndarray:
    """One 5-minute transition. h: (E, N) cm. *_mult: (N,) member perturbations."""
    E, N = h.shape
    src, dst, share = flow_idx
    sinkc = g.sink[:, None]                                   # (E,1)

    rain_cm = phys["rain_to_cm"] * rain_mm_h * rain_mult[None, :]           # (1,N) cm/tick
    runoff = g.alpha[:, None] * rain_cm * (phys.get("runoff_floor", 0.06)
        + phys["runoff_sink_gain"] * sinkc ** phys.get("sink_pow", 1.5))

    tide = tide_m + tide_off[None, :]                          # (1,N)
    imp = np.clip(tide - phys["tide_ref_m"], 0, None) * phys["tide_c"] * sinkc \
        * (g.z_min[:, None] < np.percentile(g.z_min, 25))      # only low-lying edges
    drain_k = g.kappa[:, None] * kappa_mult[None, :] * phys["drain_dt"]
    drain_k = drain_k * np.clip(1.0 - 0.6 * np.clip(tide - phys["tide_ref_m"], 0, None), 0.3, 1.0)

    f_out = phys["flow_c"] * h * (1 - sinkc * 0.8)             # sinks hold water
    q_in = np.zeros_like(h)
    if len(src):
        np.add.at(q_in, dst, f_out[src] * share[:, None])

    h_new = h + runoff + imp * 0.2 + q_in - f_out - drain_k * h
    neg = h_new < 0
    guards.clamp_count += int(neg.sum())
    h_new = np.where(neg, 0.0, h_new)
    jump = float(np.max(np.abs(h_new - h))) if E else 0.0
    guards.max_jump_cm = max(guards.max_jump_cm, jump)
    if jump > phys["jump_warn_cm"]:
        guards.jump_warns += 1
    return h_new

def run_ensemble(g: Graph, spec: dict, seed_offset: int = 0, n_members: int | None = None
                 ) -> tuple[np.ndarray, Guards]:
    """Full-horizon run -> h[t, e, n] (cm). Deterministic for a given spec+seed."""
    rng = np.random.default_rng(spec["seed"] + seed_offset)
    T, N = spec["ticks"], n_members or spec["ensemble"]
    unc, phys = spec["uncertainty"], spec["physics"]
    rain_mult = np.exp(rng.normal(0, unc["rain_mult_sigma"], N))
    kappa_mult = np.exp(rng.normal(0, unc["kappa_sigma"], N))
    tide_off = rng.normal(0, unc["tide_sigma_m"], N)
    rain = np.interp(np.arange(T), *zip(*[(t, v) for t, v in spec["rain_mm_h"]]))
    tide = np.interp(np.arange(T), *zip(*[(t, v) for t, v in spec["tide_m"]]))
    flow_idx = build_flow_index(g)
    guards = Guards()
    h = np.zeros((g.n, N), dtype=np.float64)
    out = np.zeros((T, g.n, N), dtype=np.float32)
    for t in range(T):
        if t > 0:
            h = step(h, g, phys, float(rain[t]), float(tide[t]),
                     rain_mult, kappa_mult, tide_off, flow_idx, guards)
        out[t] = h.astype(np.float32)
    return out, guards
