# Đường An VN — Reproduction Artifact

A map layer that estimates, for every road and alley edge, the probability that it is
still passable **for a specific vehicle at the time you reach it**, and routes around the
edges that are not. Pilot geography: Thủ Đức, Ho Chi Minh City. A frozen Đà Nẵng scene
tests transfer.

This folder is the reproduction package: how to rebuild everything, how to check the
numbers, and where the work stops being trustworthy.

---

## What can be checked in 30 seconds

If the repository already has its data and scenario built:

```bash
bash reproduce.sh verify
```

That runs the 122-test suite and then `verify.py`, which checks **31 claims** made in the
paper and docs against the running code and prints a pass/fail table. Every row names what
it expects; a disagreement shows up as `FAIL`, not as an argument.

```
graph: directed edges (Thu Duc)                              25809     25809  PASS
gazetteer: every entry sourced from OSM (never invented)      True      True  PASS
refusal: out-of-area market is not_found                 not_found not_found  PASS
I8: no assistant tool accepts a coordinate                   set()     set()  PASS
sensing: network length observed (%)                           0.8       0.8  PASS
rain: accumulation equals the integral of the displayed curve  True     True  PASS
charging: stations mapped inside the demo bbox                   0         0  PASS
...
31/31 claims verified
```

## Reproducing from scratch

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
bash reproduce.sh                 # fetch -> build -> simulate -> test -> verify
```

Stages, because they cost very different amounts:

| Stage | Command | Cost | Needs network |
|---|---|---|---|
| 1. Raw data | `bash reproduce.sh data` | ~50 MB, minutes | yes |
| 2. Storm scenario | `bash reproduce.sh storm` | ~590 MB, CPU-bound | no |
| 3. Tests + claims | `bash reproduce.sh verify` | seconds | no |

The scenario is **content-addressed by spec hash**: the same spec and seed produce
identical bytes (gate G2.1). That is why 590 MB of tensors are rebuilt rather than shipped
— shipping them would add size without adding trust.

To run the app itself (map, assistant, all layers):

```bash
make up && make seed && make storm     # Docker: PostGIS + Redis + API
make dev                               # http://localhost:5173
```

## Two ways this folder is used

**Inside the repository**, as committed: the scripts resolve source and data one level up.

**On its own**, after `bash pack.sh`: the bundle carries the full source, the web client,
the configuration, the documents and its own `data/`, and the scripts detect that and use
them. Verified by copying the packed folder outside the repository and running it there —
`verify.py` reports 31/31, and the API serves state, routing, charging, sensor coverage
and the ambient layer entirely from the bundle.

Requires **Python 3.12** (the version the Dockerfile pins). Some dependencies, `pyarrow`
in particular, have no wheels for newer interpreters yet.

## What is in here

```
artifact/
  README.md          this file
  verify.py          31 claim checks against the running code
  reproduce.sh       fetch -> build -> simulate -> test -> verify
  pack.sh            assemble a self-contained bundle (source snapshot + PROVENANCE)
  requirements.txt   pinned Python dependencies
  data/              1.8 MB shipped; see data/README.md for what is rebuilt instead
  code/              created by pack.sh: full source, web client, config, documents
```

Source is **not** copied into this folder by default. A second copy in git drifts from the
first the moment anyone edits the original, so `bash pack.sh` snapshots it on demand and
records the commit it came from:

```bash
bash pack.sh          # -> code/ + code/PROVENANCE (commit, branch, dirty flag, timestamp)
```

`pack.sh` refuses to build a bundle containing anything credential-shaped: it scans what
it just assembled, deletes the partial bundle and exits non-zero. Tested by planting a
fake key.

The live source lives at `../services/api` (engine and API), `../apps/web/src` (map
client), `../packages/contracts` (the OpenAPI file that generates the TypeScript types).

## Deploying

### Credentials: none ship with this artifact

There is no API key anywhere in this folder, and `pack.sh` will **refuse to build a
bundle** if it finds a credential-shaped string, exiting non-zero and deleting the partial
bundle so a mistake cannot be shipped quietly. The assistant is bring-your-own-key: a
visitor pastes their own key into the panel, the provider is inferred from its shape, and
the key travels in a request header, is never persisted or logged server-side, and lives
only in that browser tab's `sessionStorage`.

If you want the assistant enabled without visitors supplying a key, set
`ANTHROPIC_API_KEY` **in the server environment only** — never in the web build, where it
would be shipped to every visitor:

```bash
ANTHROPIC_API_KEY=... docker compose up -d      # server-side only
```

Without it the map, routing and every data layer work exactly as they do with it; only
the chat panel asks for a key.

### Option A — local, no Docker (fastest way to check the claims)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
bash reproduce.sh          # once: fetch, build, simulate
bash run_local.sh          # API on :8000, map on :5173
```

`run_local.sh stop` kills both; `run_local.sh api` starts the API alone. No PostGIS, no
Redis, no Docker.

Everything the 31 claims depend on works this way, including routing, the assistant, and
every data layer. Three things degrade, and they degrade **silently by design** — the
write paths swallow database errors so the demo survives without a database:

- citizen reports change the live map but are not persisted;
- closures and outages take effect but leave no audit entry, so
  `GET /v1/ops/override-log` always returns `[]`;
- `GET /v1/tiles/{z}/{x}/{y}.mvt` returns 500. The client uses `/v1/edges.geojson`, so the
  map itself is unaffected.

`GET /healthz` reports `"persistence": false` and lists exactly these, so the gap is
stated rather than discovered.

### Option B — everything on one host, with the database

```bash
make up && make seed && make storm
make dev            # dev server on :5173, proxied to the API on :8000
```

For a production build served by the same origin as the API, `npm run build` and point
your web server at `apps/web/dist`. No configuration needed: the client issues
root-relative `/v1/...` requests.

### Option C — static frontend, API elsewhere

This is what you want for GitHub Pages, S3, Netlify, or any CDN, with the API on a small
host (Fly.io, Render, Railway, a VM). The frontend is a static bundle; the API needs
Python plus the data.

```bash
# 1. Deploy the API somewhere with ~1 GB disk for the scenario tensors
#    (Dockerfile at services/api/Dockerfile; run make seed && make storm once)

# 2. Build the client against that API
cd apps/web
VITE_API_BASE=https://your-api.example.org npm run build

# 3. Publish apps/web/dist to any static host
```

`VITE_API_BASE` is read at build time and prefixed onto every request. Leave it unset and
behaviour is unchanged, so development and single-host deploys are unaffected. CORS is
already permissive on the API (`allow_origins=["*"]`, a local-demo setting) — **tighten it
to your actual origin before exposing the API publicly**, in `services/api/app/main.py`.

### What cannot be deployed statically

The map is not a set of pre-rendered tiles with a lookup table behind it. Routing takes
an arbitrary origin and destination and runs A* over a 25,809-edge graph against a cost
layer rebuilt for each arrival tick, and the assistant executes engine tools per turn.
Neither can be precomputed, so a static-only deployment would lose interactive routing and
the assistant, keeping only the map layers. Option C exists precisely to avoid that
trade-off.

### Sizing

| Component | Disk | Memory | Notes |
|---|---|---|---|
| API + scenario tensors | ~1 GB | ~1.5 GB | Scenario is memory-mapped per scene |
| PostGIS | ~200 MB | 512 MB | Edge table, observations, override log |
| Redis | negligible | 128 MB | Recent edge-state cache |
| Static frontend | ~2 MB | — | Any CDN |

Measured p95 route latency on the frozen build is 1.84 s; hot edge state is 0.19 s.

## Where the numbers come from

Everything `verify.py` checks was measured, not assumed. Three of the more useful ones:

**Sensing is sparse, and that is the premise.** 38 simulated sensors reach 161 of 25,809
edges — **0.8% of the network by length**. Coverage here means the engine's own
assimilation footprint (up to three graph hops within one basin, decay 1 / 0.6 / 0.35 /
0.2), not an invented camera cone, and a test asserts the served footprint equals that
function exactly. Every band outside that 0.8% is inference. The map shows it rather than
implying it.

**Most of the alley network is modelled on defaults.** `data_quality` counts the two OSM
tags that feed the passability envelope: width and surface. It takes exactly three values
— 0.50 on 18,542 edges (71.8%), 0.75 on 7,263, 1.00 on four. Those 18,542 edges are
inferred, not measured, and the layer draws three discrete steps rather than a continuous
ramp that would imply resolution the field does not have.

**The assistant cannot author geography.** No tool accepts a latitude or longitude; place
names resolve against an OSM-built gazetteer, and an unresolvable or out-of-area name is
refused rather than approximated. This is enforced by a test over the tool schemas, not by
prompt text. The reason is measured elsewhere: published benchmarks put LLM city-level
identification from raw coordinates below 25% for every model tested, and worse again on
non-English toponyms in under-represented regions — which is exactly Thủ Đức.

## Known limits

Stated here rather than left for a reviewer to discover.

1. **Live model quality is unverified on the shipped model.** The Anthropic quota is
   exhausted until 2026-09-01. The pipeline reaches the provider and degrades correctly,
   and the architecture was probed with an alternative model, but the production model's
   answer quality has not been drilled.
2. **CORS is wide open by default.** `allow_origins=["*"]` is a local-demo setting and
   must be narrowed before the API is exposed publicly.
3. **Ambient resolution is coarser than the scene.** ~8-11 km source cells over a 6.6 km
   area. Stated in the panel rather than smoothed away.
4. **No mapped EV charging in either demo area.** A data gap, not an absence of stations.
5. **The flood state is simulated.** Real deployment needs FEDS/1022 integration and a
   data-sharing agreement; nothing here claims otherwise, and every synthetic value is
   labelled.
6. **Scenario shape.** In the current storm the demo origin–destination pair is compliant
   at ticks 0–10 and never again within 48 ticks. "Wait and it clears" is therefore not
   universally available, and the assistant reports the window it searched instead of
   promising one.

## Licences

Code: this work. Data: OpenStreetMap under **ODbL** (road graph, gazetteer, POIs, charging
stations — attribution shown in the map corner); Copernicus GLO-30 under its free-use
terms (elevation); Open-Meteo under **CC-BY 4.0**, non-commercial free tier (weather and
air quality). Redistribution of the derived edge graph is share-alike under ODbL.

## Companion documents

Paths depend on how you received this folder. Inside the repository they are one level
up (`../proposal.tex`); in a packed bundle they are under `code/` (`code/proposal.tex`).

| File | What it covers |
|---|---|
| `proposal.tex`, `proposal.pdf` | The proposal: problem, contributions C1–C7, RQ1–RQ6, evaluation design |
| `technical.tex`, `technical.pdf` | **The technical reference for this artifact**: stack, data pipeline, algorithms, API surface, the prompt layer, and its own known-limits section |
| `docs/DATA_REGISTER.md` | Every source with licence, retention, and provenance tag |
| `docs/AI_FEATURES.md` | The conversational layer: grounding, evidence, what was rejected |
| `docs/MODEL_CARD.md` | Scope, limitations, incident status |
