# ROUTING_ANALYSIS

Phase 2. Read-only analysis of the routing stack: `app/engine/router.py`,
`graph.py`, `passability.py`, `state.py`. All line references are to the code as it
stands after the Phase 1 de-scope (the de-scope touched only `main.py`, the mount
layer, and file-encoding arguments; no routing logic was modified).

All measurements in §B and §C were taken on the live stack: scene `thuduc`,
**25,811 directed edges**, 11,944 nodes, ensemble `(49, 25811, 32)` float32,
spec hash `5ad137a14513`.

---

## A. Current algorithm

### A.1 Graph model

`graph.py:8-31` defines `Graph` as struct-of-arrays: every attribute is a NumPy array
indexed by edge, not a per-edge Python object.

- **Directed edges.** `build_graph.py` emits one edge per direction: an OSM way that is
  not `oneway` produces `{way_id}-{seg}-f` and `{way_id}-{seg}-b` with reversed
  coordinates. Ways are split at intersections and chunked to `MAX_SEG_M = 250 m`, so an
  edge is short enough to carry a single water-depth state.
- **Adjacency.** `out_edges: dict[node, list[edge_idx]]` (`graph.py:75-76`) and
  `v_int: list[int]` (`graph.py:74`), a plain-int copy of the head-node array kept
  specifically so the search loop does no NumPy scalar boxing.
- **Measured shape.** 25,811 edges over 11,944 nodes; mean out-degree **2.16**,
  p95 = 3, max = 5. This is a sparse street graph, not a dense mesh.
- **Free-flow travel time** is the only time term: `travel_time_s = length_m / (speed_kmh / 3.6)`
  (`graph.py:30-31`). There is no congestion model, no turn cost, no traffic-signal
  penalty, and no turn restriction. Two edges meeting at a node are always connectable.

`downhill` (`graph.py:78-82`) is a second adjacency used only by the hydrology, not by
routing: successor edges whose `z_min` is not more than 5 cm above the current edge.

### A.2 State that routing consumes

Routing never reads water depth directly. It reads a posterior produced by `state.py`:

1. The precomputed ensemble `ens[t, e, n]` (cm) is the **prior** (`state.py:25-31`).
2. Observations reweight ensemble members per edge-neighbourhood. `neighbourhood(e)`
   (`state.py:59-79`) spreads influence at most 3 hops with decay
   `HOP_DECAY = [1.0, 0.6, 0.35, 0.2]` (`state.py:15`), constrained to the same basin by
   `BASIN_DZ = 2.0 m` (`state.py:16`).
3. `weights(tick)` (`state.py:129-143`) produces a per-edge, per-member weight matrix
   `W (E, N)` by softmax over influence-weighted log-likelihoods.
4. `quantiles(tick)` (`state.py:172-194`) gives weighted p10/p50/p90 per edge.

**Passability** (`passability.py`):

```
member_passability(h, v) = sigmoid((refuse_v - h) / SIGMOID_SCALE)     # passability.py:21-24
pi(e, t, v)              = sum_n member_passability(ens[t,e,n], v) * W[e,n]   # passability.py:26-35
```

with `SIGMOID_SCALE = 2.5 cm` (`passability.py:18`). `pi` is forced to 0 where the
vehicle has no access (`passability.py:33`).

**Vehicle envelope** (`passability.py:12-17`), conservative still-water thresholds
`(caution_cm, refuse_cm)`:

| vehicle | caution | refuse |
|---|---|---|
| `motorbike` | 10.0 | 20.0 |
| `e_2w` | 8.0 | 15.0 |
| `car` | 15.0 | 25.0 |
| `response` | 25.0 | 40.0 |

Only `refuse` enters the cost path; `caution` is presentation-only. The envelope reaches
routing through exactly two channels — the sigmoid that defines `pi`, and the hard block
at `AVOID_PI`. There is no continuous "this vehicle dislikes water more" term.

**Risk band** (`passability.py:37-51`) maps `(pi, width_cm, age_s, has_sources, closed)`
to `low | unknown | uncertain | avoid`. The band is **not** an input to the cost
function. Routing reads `pi`, `cvar`, and `width` directly; the band is what the map and
the inspector render, and what `explanation` in the `/v1/routes` response cites. This
matters for §D: "inject the risk band as an edge weight" describes what a future
integration would do, not what happens today.

### A.3 Per-tick cost ingredients

`_tick_layer` (`router.py:26-52`), cached on the scenario per `(vehicle, tick, version)`:

```
unsafe[e,n]   = 1 - member_passability(ens[t,e,n], v)
p_unsafe[e]   = sum_n unsafe[e,n] * W[e,n]
p_constraint  = p_unsafe where p_unsafe > P_NOISE_FLOOR else 0        # router.py:20,36
thr[e]        = quantile_n(ens[t,e,:], 0.90)
CVaR90[e]     = sum_n unsafe*W*[ens >= thr] / sum_n W*[ens >= thr]    # router.py:38-40
width_norm[e] = clip((p90 - p10) / 20, 0, 1)                          # router.py:41-42
blocked[e]    = (pi < AVOID_PI) or not access[v]                      # router.py:43-44
```

Constants, verbatim from source:

| constant | value | line |
|---|---|---|
| `ALPHA` | `motorbike/e_2w/car = 0.05`, `response = 0.20` | `router.py:16` |
| `P_NOISE_FLOOR` | `0.01` | `router.py:20` |
| `L1, L2` | `6.0, 1.2` | `router.py:21` |
| `AVOID_PI` | `0.55` | `router.py:22` |
| `RETRY_MULT` | `[1.0, 4.0, 16.0]` | `router.py:23` |
| `WAIT_OFFSETS` | `[3, 6, 12, 18]` ticks | `router.py:24` |
| `VMAX_MS` | `80 / 3.6` m/s | `router.py:113` |
| `SNAP_MAX_M` | `300.0` | `router.py:98` |
| `SCAN_STEP` | `3` ticks | `router.py:284` |

`P_NOISE_FLOOR` deserves a note: it zeroes per-edge unsafety below 0.01 **for the
constraint only**, not for the cost. Without it the union bound would accumulate sigmoid
tail noise across a long path and reject routes for being long rather than risky. The
constraint therefore measures genuinely risky edges; the objective still sees the tail.

### A.4 The A* variant

`_search` (`router.py:149-212`) is A* over **nodes**, with edge costs that depend on the
tick at which the search believes it reaches that node.

**Objective** (`router.py:137`, applied when `flood_aware`):

```
cost(e, t) = tt(e) * (1 + L1 * risk_mult * CVaR90(e, t) + L2 * width_norm(e, t))
           = tt(e) * (1 + 6.0 * m * CVaR90 + 1.2 * width_norm)
```

When `flood_aware=False` the cost is plain `tt(e)` and the blocked set is only
inaccessible edges plus closures (`router.py:139-141`).

**Heuristic** (`router.py:157-162`):

```
h(node) = haversine(node, dst) / VMAX_MS,   VMAX_MS = 22.22 m/s
```

Admissible: `cost(e, t) >= tt(e)` always, because `L1`, `L2`, `CVaR90` and `width_norm`
are all non-negative, so straight-line distance at the fastest road speed can never
overestimate. Consistency holds for the same reason on a metric embedding. Note the
heuristic is a **pure travel-time** bound while the objective is travel time *plus*
risk penalties — so as the risk multiplier rises the heuristic becomes progressively
weaker relative to the true cost, and the search degrades toward Dijkstra. This is a
performance property, not a correctness one.

**Time dependency** (`router.py:176-177`): at each settled node the search computes an
arrival tick and fetches that tick's layer. Cost layers are therefore sampled at 5-minute
resolution along the path, and a multi-stop trip departs each leg at the previous leg's
arrival tick (`_chain`, `router.py:225-237`).

**Chance constraint.** `risk_acc` accumulates `p_constraint` per node
(`router.py:185-186`), and the path is accepted only if

```
sum_{e in path} p_unsafe(e, t_arr(e)) <= ALPHA[vehicle]
```

checked in `route()` at `router.py:254`. This is a union bound on
`P(at least one edge is unsafe)`, which is conservative — it ignores the strong spatial
correlation between neighbouring flooded edges, so it over-states joint risk. For a
safety-first product that direction of error is the defensible one.

**Blocking versus pricing.** Edges with `pi < 0.55` and official closures are removed
from the search entirely (`router.py:44-48`), not made expensive. The policy in the
module docstring is explicit: unsafe edges "are not *expensive*, they are not offered".

### A.5 Retry escalation and refusal

`route()` (`router.py:239-278`) runs this sequence:

1. **Dry baseline**: `_chain(..., risk_mult=0.0, flood_aware=False)` → the `fastest_dry`
   route, used only for comparison.
2. **Escalation**: for `m` in `[1.0, 4.0, 16.0]`, run a flood-aware chain and accept the
   first candidate whose `sum_p_unsafe <= alpha`.
3. **Early exit**: if any multiplier returns `None`, the search stops immediately
   (`router.py:249-253`). The reasoning is sound — the blocked set does not depend on
   `risk_mult`, so a connectivity failure at one multiplier is a failure at all of them.
4. **Refusal**: if no multiplier satisfies the constraint, `recommended` is `None` and
   `status` becomes `no_safe_route` (`routes.py:48`).
5. **Wait probe**: only on refusal, two offsets are tried — `WAIT_OFFSETS[1:3]` = 6 and
   12 ticks = **30 and 60 minutes** (`router.py:262`). The response carries
   `wait_probed_offsets_min` and `wait_search_is_partial: true`
   (`router.py:275-278`) so a null `wait` cannot be read as "no departure exists".

Escalation raises the *penalty weight*, never the *risk tolerance*: `alpha` is fixed per
vehicle. A higher `m` buys a more detour-willing search, not a laxer safety bar. The
thorough alternative, `departure_window()` (`router.py:296-358`), scans coarse-to-fine at
`SCAN_STEP = 3` ticks and is reachable through the assistant, not through `POST /v1/routes`.

---

## B. Behavioral regimes (measured)

Sweep: 4 landmark OD pairs (6 unordered combinations) × 25 ticks (0..48 step 2) ×
2 vehicles = **300 probes** against the running API. Landmarks resolved through the
gazetteer: Kha Vạn Cân `[106.754174, 10.853772]`, Chợ Thủ Đức `[106.754197, 10.850238]`,
Võ Văn Ngân `[106.764336, 10.850399]`, Ga Bình Thái `[106.763894, 10.832652]`.

```
probes=300   ok=190   no_safe_route=110   of which wait offered=57
```

### Regime A — recommendation identical to fastest-dry (167 / 190 = 88% of successes)

`added_time_s == 0`. Either no edge on the fastest path carries meaningful risk, or the
risky edges are already blocked and the dry route was computed on a graph that never
included them. The elaborate cost model changes nothing here.

### Regime B — marginal reroute (13 / 190 = 7%)

`0 < added_time_s <= 15 s`. Example, tick 36, motorbike, Kha Vạn Cân → Ga Bình Thái:

```
fastest_dry       440.6 s   risk_exposure 4.4 s   max_edge_risk 0.2839
recommended       448.1 s   risk_exposure 1.0 s   max_edge_risk 0.0207
comparison        added_time_s 7.4    avoided_exposure_s 3.4
explanation       239958984-0-b  NO_COVERAGE  band=uncertain, p50=15.0cm, pi=0.679
```

A 1.7% time cost removes 93% of the worst-edge risk. This is the regime the cost model
is actually built for, and it is rare in the sweep.

### Regime C — meaningful reroute (10 / 190 = 5%)

`added_time_s > 15 s`. The two most pronounced cases found — these are the candidates for
`DEMO_SCRIPT`:

| # | vehicle | tick | OD | dry | recommended | added | max_edge_risk |
|---|---|---|---|---|---|---|---|
| 1 | `motorbike` | **16** | Ga Bình Thái → Kha Vạn Cân | 420.3 s | 549.4 s | **+129.1 s (+31%)** | 0.081 → **0.019** (−77%) |
| 2 | `car` | **20** | Ga Bình Thái → Kha Vạn Cân | 420.3 s | 540.8 s | **+120.5 s (+29%)** | 0.072 → **0.022** (−69%) |

Case 1 is the strongest single demonstration in the scene: a 7-minute trip becomes a
9-minute trip and the worst edge on the path drops by more than a factor of four. Note it
sits at tick 16, on the *leading edge* of the storm — before the network fragments and
the answer collapses to refusal.

### Regime D — refusal (110 / 300 = 37% of all probes)

`no_safe_route`. Windows per OD, motorbike:

```
Cho Thu Duc  -> Kha Van Can    ticks 16-44
Cho Thu Duc  -> Ga Binh Thai   ticks 16-40
Cho Thu Duc  -> Vo Van Ngan    ticks 16-40
Ga Binh Thai -> Kha Van Can    ticks 18-36
Ga Binh Thai -> Vo Van Ngan    ticks 18-34
Kha Van Can  -> Vo Van Ngan    ticks 18-34
```

and car:

```
Cho Thu Duc  -> Kha Van Can    ticks 18-40
Cho Thu Duc  -> Ga Binh Thai   ticks 18-36
Cho Thu Duc  -> Vo Van Ngan    ticks 18-36
Ga Binh Thai -> Kha Van Can    ticks 22-28
Ga Binh Thai -> Vo Van Ngan    ticks 24-28
Kha Van Can  -> Vo Van Ngan    ticks 24-26
```

Two observations worth stating plainly:

- **Car refusal windows are strictly narrower than motorbike windows** on every OD pair.
  That follows directly from the envelope table (`car` refuses at 25 cm, `motorbike` at
  20 cm) and is internally consistent, but it encodes a claim — that a car is the safer
  choice in a flooded street — that still-water depth alone cannot support. Cars stall
  and float; the model has no term for either. `MODEL_CARD.md` already states that flow
  velocity is not modelled. This ordering is the visible consequence, and a demo that
  shows it should say so out loud.
- **Chợ Thủ Đức is the bottleneck node**, refusing across the widest tick window on both
  vehicles. It is the OD whose surrounding edges flood first and clear last.

`wait_suggestion` appeared in 57 of the 110 refusals. It is produced only when a probe at
depart+30 min or depart+60 min clears `alpha` (`router.py:260-270`), so its absence in
the other 53 means "not found at two offsets", not "no departure exists".

---

## C. Complexity and scale limit

### C.1 Measured cost at district scale (25,811 edges)

Live HTTP, warm caches:

```
POST /v1/routes  (motorbike, 1 leg)          n=30   p50 = 30.1 ms   p95 = 94.7 ms   max = 127.6 ms
POST /v1/routes  (include_conservative=true) n=20   p50 = 67.0 ms                   max = 127.4 ms
```

In-process, cold (caches cleared):

```
_tick_layer(t=22)             cold 102.3 ms      cached 0.006 ms
_fast_layer (numpy -> lists)  1.4 ms
_search single A*             327.0 ms cold
route() full chain            266.9 ms cold
```

The gap between 30 ms warm and ~300 ms cold is the whole performance story: the startup
thread `passability.warm()` (`routers/passability.py:9-27`) precomputes
**49 ticks × 4 vehicles = 196 layers** before the first user query, and interactive
latency is a cache read.

### C.2 Asymptotics

Let `E` = edges, `N` = ensemble members, `T` = ticks, `V` = vehicles.

| stage | complexity | at E=25,811 | at E=1,000,000 |
|---|---|---|---|
| ensemble tensor | `O(T·E·N)` float32 | 161.9 MB | **6.3 GB** |
| `_tick_layer` (one tick, one vehicle) | `O(E·N)` | 102 ms | ~4.0 s |
| `warm()` full precompute | `O(T·V·E·N)` | ~20 s | **~13 min** |
| `_fast_layer` Python-list entry | `O(E)` boxed floats | 2.5 MB | ~97 MB |
| A* search | `O((V_n + E) log V_n)` | ~30 ms warm | see below |

### C.3 Where it breaks, specifically

**1. The ensemble tensor is the hard wall.** 161.9 MB at 25,811 edges scales linearly:
a million-edge city is 6.3 GB of float32 for a single scene and a single scenario. It is
`mmap`-ed (`state.py:26-27`), so it does not all have to be resident — but `_tick_layer`
touches `ens[tick]` in full (`router.py:33`), which is a 3.2 MB slice today and 125 MB
per tick at city scale. Every uncached tick becomes a page-fault storm.

**2. `_fast_layer` converts NumPy arrays to Python lists.** `router.py:142-143` calls
`.tolist()` on three E-length arrays to keep the A* inner loop free of NumPy scalar
boxing. That is the right trade at 25,811 edges — measured at 1.4 ms and 2.5 MB per
entry. At a million edges each cache entry is ~97 MB of boxed Python floats.

**3. The cache bound counts entries, not bytes.** `router.py:144-145` and
`passability.py:92-93` both evict when `len(sc._pi_cache) > 900`. The cache holds three
kinds of value with very different sizes: tick layers, fast layers, and serialised edge
states. 900 fast-layer entries at today's size is already ~2.2 GB if the cache ever
filled with them; at city scale a single-digit number of entries would exhaust memory.
The demo never hits this because `warm()` populates a predictable ~200 layers and the
key space is small, but the bound does not express the constraint it needs to.

**4. A* degrades toward Dijkstra as the risk multiplier rises.** The heuristic
(`router.py:157-162`) bounds *travel time*; the objective is travel time plus risk
penalties. Measured ratio of `cost/tt` across the graph at tick 22:

```
risk_mult =  0.0   mean 1.21   p95  1.85   max  2.20
risk_mult =  1.0   mean 1.97   p95  7.67   max  8.20
risk_mult =  4.0   mean 4.25   p95 25.14   max 26.20
risk_mult = 16.0   mean 13.34  p95 95.03   max 98.20
```

At `m = 16` the heuristic under-estimates true cost by more than an order of magnitude on
most edges, so it prunes almost nothing. Since escalation runs up to three chained
searches, the worst case is three near-Dijkstra sweeps of the graph. At district scale
that is the 127 ms p95 above. At a million edges, expect seconds per query.

**5. Arrival tick is derived from penalized cost, not travel time.** `router.py:176`
computes `arr_tick = depart_tick + int(dist[node] // tick_s)`, and `dist` accumulates
`cost[e]`, which includes the risk penalty. The search therefore believes it has
travelled further into the storm than it has. Measured on Ga Bình Thái → Kha Vạn Cân,
departing tick 16:

| `risk_mult` | true travel | search-perceived elapsed | inflation |
|---|---|---|---|
| 0.0 | 420.3 s (1.4 ticks) | 489.4 s (1.6 ticks) | ×1.2 |
| 1.0 | 440.6 s (1.5 ticks) | 549.6 s (1.8 ticks) | ×1.2 |
| 4.0 | 488.4 s (1.6 ticks) | 715.0 s (2.4 ticks) | ×1.5 |
| 16.0 | 549.4 s (1.8 ticks) | 1296.0 s (4.3 ticks) | **×2.4** |

On a 7-minute trip this is a ~12-minute lookahead error and mostly harmless, because the
flood field changes slowly relative to the trip. The error grows with both trip length
and risk multiplier. On a 45-minute city-scale trip at `m = 16` the perceived elapsed time
would exceed the 48-tick (245-minute) horizon and saturate at the last tick — the search
would cost every edge against the end-of-storm state regardless of when it is reached.
This is a correctness issue that district-scale geometry currently hides.

**6. Snapping is a linear scan.** `snap` (`router.py:90-92`) does
`argmin` over all core-node coordinates on every call — `O(nodes)` per snap, 11,944 today
and a million-plus at city scale, per origin, per destination, per waypoint. It needs a
spatial index long before the search does.

---

## D. Development direction

No code changes are proposed here. These are options with their costs stated.

### D.1 Keep A* at district scale

For a bounded pilot — one district, tens of thousands of edges, a 4-hour horizon — the
current design is appropriate and should not be replaced. 30 ms p50 is comfortably
interactive, the precompute is 20 seconds, and time-dependent costs with a per-query
ensemble posterior are genuinely hard to express in an off-the-shelf engine. The
integration cost of an external router would buy nothing at this size.

The two things worth fixing at this scale, in order, are both from §C and neither is a
rewrite: **arrival tick should be tracked from true travel time**, kept separately from
the search's cost accumulator (§C.3-5), and **the cache bound should count bytes**
(§C.3-3).

### D.2 City scale: two routes, compared

**Option (a) — risk band as a custom edge weight in OSRM or Valhalla.**

Both engines support per-edge cost customisation: Valhalla through dynamic costing plus
its traffic//live-speed overlay, OSRM through a traffic-update file over a
contraction-hierarchy build. The pipeline becomes: engine computes per-edge risk →
project to a scalar penalty → push as an edge-weight update → let a mature router handle
the search.

- **Gains.** Turn restrictions, turn costs, road hierarchy, map-matching, alternatives,
  isochrones and years of correctness work on real OSM geometry — all things this codebase
  does not have and would otherwise have to build. Query time at city scale drops to
  single-digit milliseconds.
- **Costs.** Both engines want a *scalar* weight per edge. The current model is not
  scalar: it carries `p_unsafe`, `CVaR90`, and `width_norm` separately, and it enforces a
  **path-level** constraint (`sum p_unsafe <= alpha`) that no edge weight can express. You
  would flatten the objective into one number and lose the chance constraint, or
  approximate it with a Lagrangian penalty and lose the guarantee. Time dependency is also
  awkward: OSRM's traffic updates are a whole-graph reload, so a 5-minute tick means
  rebuilding or hot-swapping the weight set every tick.
- **The blocking policy survives intact.** `pi < 0.55` edges become unroutable rather than
  expensive — both engines express that cleanly as an infinite weight or an access
  restriction. The part that survives the port is the part that matters most for safety.

**Option (b) — implement Contraction Hierarchies in-house.**

- **Gains.** Full control over the cost model; the chance constraint and time-dependence
  stay first-class.
- **Costs.** CH assumes a *static* metric. Time-dependent CH exists but is substantially
  harder, and a metric that changes every 5 minutes with the flood posterior invalidates
  the shortcut set. Customizable Route Planning (CRP) is the better fit for
  frequently-changing metrics — it separates a slow topology preprocess from a fast metric
  customisation — but implementing CRP correctly is a multi-month effort by people who
  have done it before. Building this instead of acquiring real flood data would be the
  wrong order.

**Recommendation.** For a city-scale deployment, option (a) with the chance constraint
demoted to a post-hoc check: let the external engine return k alternatives against a
flattened risk weight, then score each alternative against the real ensemble in this
codebase and reject those exceeding `alpha`. That keeps the safety argument in code we
control while handing the search to an engine that is good at it. It is a hybrid, and the
honest description of it is that the guarantee becomes "best of k checked" rather than
"optimal subject to constraint".

### D.3 Where this is over-engineered

Stated plainly, because it is the most useful thing in this document.

**The cost model is more sophisticated than its inputs justify.** CVaR at the 90th
percentile, a union-bound chance constraint, a per-edge uncertainty-width penalty and a
three-step retry escalation are all computed on top of a **synthetic** ensemble: a storm
spec in a YAML file, observations drawn from a designated truth run through a Gaussian
noise model (`sim/storm.py:15-36`), and drainage priors that are a deterministic function
of DEM sink score plus `rng.normal(0, 0.01)` (`attach_terrain.py`). `MODEL_CARD.md` is
already explicit that drainage capacity is a latent prior and not measured pipe data.

The measurements in §B make the imbalance concrete: **88% of successful queries return a
route identical to the fastest-dry route**, and 5% show a meaningful reroute. The
elaborate machinery is deciding a different answer in one query in twenty, on data whose
generating process is known and synthetic. Tuning `L1 = 6.0` against this input optimises
against the storm spec, not against Thủ Đức.

**Correct priority order:**

1. **Real observations.** One real gauge series, or a handful of validated flood reports
   with timestamps, changes what can be claimed more than any cost-function change. The
   `observations` endpoint and the interval-observation likelihood (`state.py:96-99`)
   already accept them; the interface exists and is unused by real data.
2. **Real drainage and terrain.** GLO-30 at 30 m cannot resolve the alley microtopography
   that determines where water actually stands, and 21,067 of 25,811 edges are alley-class.
   This is the single largest error source in the stack.
3. **Calibration against a recorded event.** Even one historical flood with known
   inundation extent turns `sink_score` from a plausible proxy into something with a
   measured skill score.
4. **Only then, the cost model.** Re-tune `L1`, `L2`, `alpha`, and the CVaR quantile
   against real outcomes. Until steps 1-3 exist, these are free parameters fitted to a
   simulation of themselves.

The two §D.1 fixes are exceptions to this ordering only because they are bug-shaped
rather than tuning-shaped: the arrival-tick inflation produces wrong answers on long
trips regardless of what the input data is.

### D.4 Rendering path, held for scale

`routers/tiles.py` serves Mapbox Vector Tiles from PostGIS via `ST_AsMVT`. It is switched
**off** in the Phase 1 de-scope (`DEMO_FEATURES["tiles"] = False`) because the demo UI
reads the whole scene from the static `/v1/edges.geojson` and the local dev path has no
PostGIS. That decision is about the demo, not about the architecture: shipping 25,811
edges as one GeoJSON document is fine and shipping a million is not. The MVT path is the
city-scale rendering answer, already written, and it is the first thing to switch back on
when the scene outgrows a single document. The same applies to the per-tick edge-state
payload from `/v1/state`, which is a full-scene aligned array today and would need the
same tiling treatment.
