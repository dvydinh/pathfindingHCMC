"""Scenario runtime: precomputed ensemble + live assimilation overlay.

The precomputed ensemble is the PRIOR. Simulated feed observations (and, from M5,
user reports) reweight ensemble members per edge-neighbourhood — observations update
only a hydrologically/topologically local region (proposal C2/C3). Interactive events
(closures, outages) are applied at query time; closures AFTER inference (invariant I4).
"""
from __future__ import annotations
import json, functools, math, threading
from collections import deque
import numpy as np
from ..deps import DATA
from . import graph

HOP_DECAY = [1.0, 0.6, 0.35, 0.2]      # influence by graph distance (hops)
BASIN_DZ = 2.0                          # same-basin proxy: |z difference| < 2 m
STALE_S = 1800                          # evidence considered stale after 30 min

class Scenario:
    def __init__(self, scene: str):
        self.scene = scene
        meta = json.loads((DATA / "scenarios" / f"{scene}_meta.json").read_text(encoding="utf-8"))
        self.meta = meta
        base = DATA / "scenarios" / f"{scene}_{meta['spec_hash']}"
        if (base.parent / (base.name + "_ens.npy")).exists():
            self.ens = np.load(base.parent / (base.name + "_ens.npy"), mmap_mode="r")
            self.truth = np.load(base.parent / (base.name + "_truth.npy"), mmap_mode="r")
        else:  # fall back to the compressed artifact
            npz = np.load(base.parent / (base.name + ".npz"))
            self.ens = npz["ensemble"]      # (T, E, N) cm
            self.truth = npz["truth"]       # (T, E) cm — OSSE ground truth, eval only
        self.T, self.E, self.N = self.ens.shape
        self.tick_s = meta["tick_minutes"] * 60
        self.g = graph.load(scene)
        assert self.g.n == self.E
        # live interactive state
        self.lock = threading.Lock()
        self.closures: set[int] = set()
        self.outages: set[str] = set()
        self.user_obs: list[dict] = []
        self.version = 0                    # bumped on any interactive change
        self._nbhd_cache: dict[int, dict[int, float]] = {}
        self._node_adj = self._build_node_adj()
        self._w_cache: dict = {}
        self._q_cache: dict = {}
        self._pi_cache: dict = {}
        self._obs_cache: dict = {}
        self.recent_routes: deque = deque(maxlen=200)   # edge sets of recent queries (C6)

    # ---------- topology ----------
    def _build_node_adj(self) -> dict[int, list[tuple[int, int]]]:
        adj: dict[int, list[tuple[int, int]]] = {}
        g = self.g
        for i in range(g.n):
            adj.setdefault(int(g.u[i]), []).append((int(g.v[i]), i))
            adj.setdefault(int(g.v[i]), []).append((int(g.u[i]), i))
        return adj

    def neighbourhood(self, e: int) -> dict[int, float]:
        """Edges within 3 hops of edge e, same-basin constrained, with hop decay."""
        if e in self._nbhd_cache:
            return self._nbhd_cache[e]
        g = self.g
        z0 = g.z_min[e]
        seen_nodes = {int(g.u[e]): 0, int(g.v[e]): 0}
        out = {e: HOP_DECAY[0]}
        frontier = [int(g.u[e]), int(g.v[e])]
        for hop in range(1, len(HOP_DECAY)):
            nxt = []
            for node in frontier:
                for (n2, ei) in self._node_adj.get(node, []):
                    if abs(g.z_min[ei] - z0) < BASIN_DZ and out.get(ei, 0) < HOP_DECAY[hop]:
                        out[ei] = max(out.get(ei, 0.0), HOP_DECAY[hop])
                    if n2 not in seen_nodes:
                        seen_nodes[n2] = hop
                        nxt.append(n2)
            frontier = nxt
        self._nbhd_cache[e] = out
        return out

    # ---------- observations ----------
    def observations_upto(self, tick: int) -> list[dict]:
        obs = [o for o in self.meta["feeds"]
               if o["tick"] <= tick and o["feed_id"] not in self.outages]
        obs += [o for o in self.user_obs if o["tick"] <= tick]
        return obs

    def _log_lik(self, o: dict, tick: int) -> np.ndarray:
        """log-likelihood per ensemble member at the obs edge, decayed by age."""
        h = self.ens[o["tick"], o["edge"], :].astype(np.float64)
        decay = 0.5 ** ((tick - o["tick"]) / self.meta.get("obs_decay_ticks", 6))
        if "depth_cm" in o:
            sig = max(o.get("noise_cm", 4.0), 1.0)
            ll = -0.5 * ((h - o["depth_cm"]) / sig) ** 2
        else:  # interval observation (categorical, M5)
            lo, hi = o["interval_cm"]
            soft = 3.0
            ll = np.log(1e-9 + _sig((h - lo + soft) / soft) * _sig((hi + soft - h) / soft))
        return ll * decay

    # ---------- vectorised obs -> edge influence ----------
    def _obs_arrays(self, tick: int):
        """(ll_matrix (O,N), scatter edge_idx, scatter obs_idx, scatter infl,
        last_tick (E,)) for all obs <= tick — fully vectorised."""
        key = (tick, self.version)
        if key in self._obs_cache:
            return self._obs_cache[key]
        obs = self.observations_upto(tick)
        last = np.full(self.E, -1, dtype=np.int32)
        if not obs:
            out = (np.zeros((0, self.N)), np.zeros(0, np.int64), np.zeros(0, np.int64),
                   np.zeros(0), last)
            self._obs_cache = {key: out}
            return out
        ll = np.stack([self._log_lik(o, tick) for o in obs])       # (O, N)
        e_idx, o_idx, infl = [], [], []
        for oi, o in enumerate(obs):
            for e, w in self.neighbourhood(o["edge"]).items():
                e_idx.append(e); o_idx.append(oi); infl.append(w)
                if o["tick"] > last[e]:
                    last[e] = o["tick"]
        out = (ll, np.array(e_idx), np.array(o_idx), np.array(infl), last)
        if len(self._obs_cache) > 8:
            self._obs_cache.clear()
        self._obs_cache[key] = out
        return out

    # ---------- posterior weights ----------
    def weights(self, tick: int) -> np.ndarray:
        key = (tick, self.version)
        if key in self._w_cache:
            return self._w_cache[key]
        ll, e_idx, o_idx, infl, _ = self._obs_arrays(tick)
        S = np.zeros((self.E, self.N))
        if len(e_idx):
            np.add.at(S, e_idx, infl[:, None] * ll[o_idx])
        S -= S.max(axis=1, keepdims=True)
        W = np.exp(S)
        W /= W.sum(axis=1, keepdims=True)
        if len(self._w_cache) > 64:
            self._w_cache.clear()
        self._w_cache[key] = W
        return W

    def last_obs_tick(self, tick: int) -> np.ndarray:
        """Per edge: most recent obs tick with influence, or -1."""
        return self._obs_arrays(tick)[4]

    def source_mix(self, tick: int, e: int, window: int = 12) -> dict[str, int]:
        mix: dict[str, int] = {}
        for o in self.observations_upto(tick):
            if tick - o["tick"] <= window and e in self.neighbourhood(o["edge"]):
                mix[o["source_class"]] = mix.get(o["source_class"], 0) + 1
        return mix

    def conflict_edges(self, tick: int, window: int = 6) -> set[int]:
        """Edges under influence of near-simultaneous observations that disagree."""
        recent: dict[int, list[float]] = {}
        for o in self.observations_upto(tick):
            if tick - o["tick"] <= window and "depth_cm" in o:
                recent.setdefault(o["edge"], []).append(o["depth_cm"])
        conf: set[int] = set()
        keys = list(recent)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                na, nb = self.neighbourhood(a), self.neighbourhood(b)
                shared = set(na) & set(nb)
                if shared and abs(max(recent[a]) - min(recent[b])) > 12:
                    conf |= shared
        return conf

    def quantiles(self, tick: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Weighted p10/p50/p90 per edge (posterior). Cached per (tick, version)."""
        key = (tick, self.version)
        if key in self._q_cache:
            return self._q_cache[key]
        skey = ("sorted", tick)             # sort is version-independent — cache it
        if skey not in self._q_cache:
            h = np.asarray(self.ens[tick], dtype=np.float32)
            order = np.argsort(h, axis=1)
            self._q_cache[skey] = (np.take_along_axis(h, order, axis=1), order)
        hs, order = self._q_cache[skey]
        W = self.weights(tick)
        ws = np.take_along_axis(W, order, axis=1)
        cw = np.cumsum(ws, axis=1)
        cw /= cw[:, -1:]
        out = []
        for q in (0.10, 0.50, 0.90):
            idx = np.argmax(cw >= q, axis=1)
            out.append(hs[np.arange(self.E), idx])
        while len(self._q_cache) > 160:
            del self._q_cache[next(iter(self._q_cache))]
        self._q_cache[key] = (out[0], out[1], out[2])
        return out[0], out[1], out[2]

    def bump(self) -> None:
        with self.lock:
            self.version += 1
            self._pi_cache.clear()
            self._w_cache.clear()
            self._q_cache = {k: v for k, v in self._q_cache.items() if k[0] == "sorted"}
            self._obs_cache.clear()

def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))

@functools.lru_cache(maxsize=2)
def get(scene: str) -> Scenario:
    return Scenario(scene)
