#!/usr/bin/env bash
# Run the whole thing locally with no Docker, for testing.
#
# Starts the API on :8000 and the map client on :5173. Everything the claims in this
# artifact depend on works this way; the parts that need PostGIS do not, and are listed at
# the end so the gap is visible rather than discovered.
#
#   bash run_local.sh          start both, stream logs, Ctrl-C to stop
#   bash run_local.sh api      API only
#   bash run_local.sh stop     kill whatever a previous run left behind
set -euo pipefail
cd "$(dirname "$0")"

# Two ways this folder gets used: sitting inside the repository, or handed over on its
# own after pack.sh. The repository wins when present -- code/ is a build output of this
# folder, and letting it shadow the real source means testing a snapshot instead of the
# thing being changed.
if [ -d "../services/api" ]; then
  REPO="$(cd .. && pwd)"                   # inside the repository
  export DATA_DIR="${DATA_DIR:-$REPO/data}"
elif [ -d "code/services/api" ]; then
  REPO="$(pwd)/code"                       # standalone bundle
  export DATA_DIR="${DATA_DIR:-$(pwd)/data}"
else
  echo "Cannot find the source: neither ../services/api nor code/services/api." >&2
  echo "If this is a standalone copy, run pack.sh from a checkout first." >&2
  exit 1
fi
export CONFIG_DIR="${CONFIG_DIR:-$REPO/config}"
export PYTHONPATH="$REPO/services/api"
PY="${PY:-python3}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
MODE="${1:-all}"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
stop_all() {
  pkill -f "uvicorn app.main" 2>/dev/null || true
  pkill -f "vite.*--port ${WEB_PORT}" 2>/dev/null || true
  pkill -f "apps/web/node_modules/.bin/vite" 2>/dev/null || true
}

if [ "$MODE" = "stop" ]; then stop_all; echo "stopped"; exit 0; fi

if ! $PY -c 'import fastapi, uvicorn, numpy, yaml' 2>/dev/null; then
  echo "Missing Python dependencies for '$PY'." >&2
  echo "  python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi
if [ ! -f "$DATA_DIR/scenarios/thuduc_meta.json" ]; then
  echo "No scenario built yet. Run:  bash reproduce.sh" >&2
  exit 1
fi

stop_all
trap stop_all EXIT INT TERM

step "API on http://localhost:${API_PORT}"
( cd "$REPO/services/api" && $PY -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" ) &
for _ in $(seq 1 40); do
  curl -sf "http://localhost:${API_PORT}/healthz" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -sf "http://localhost:${API_PORT}/healthz" >/dev/null || { echo "API did not come up" >&2; exit 1; }
echo "API ready"

if [ "$MODE" = "api" ]; then
  echo "API only. Ctrl-C to stop."; wait; exit 0
fi

step "Map client on http://localhost:${WEB_PORT}"
[ -d "$REPO/apps/web/node_modules" ] || ( cd "$REPO/apps/web" && npm ci )
( cd "$REPO/apps/web" && npm run dev -- --port "$WEB_PORT" ) &

cat <<TXT

  Map        http://localhost:${WEB_PORT}
  API docs   http://localhost:${API_PORT}/docs

  Everything the claims in this artifact depend on works here: the map and every layer,
  routing, the assistant, weather and rainfall, air and heat, charging, sensor coverage,
  closures and outages, and citizen reports (which do update live state).

  What is quietly missing without PostGIS - checked, not assumed:
    * citizen reports change the map but are not persisted
    * closures and outages take effect but leave no audit entry
    * GET /v1/ops/override-log therefore always returns []
    * GET /v1/tiles/{z}/{x}/{y}.mvt returns 500 - the client uses /v1/edges.geojson,
      so the map itself is unaffected

  These degrade silently by design (the write paths swallow database errors so the demo
  survives), which is why GET /healthz reports "persistence": false and lists them.
  For the full stack:  make up && make seed && make storm

  Ctrl-C to stop both.
TXT
wait
