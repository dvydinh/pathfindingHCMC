#!/usr/bin/env bash
# End-to-end reproduction. Run from the artifact/ directory.
#
# Stages are separated because they cost very different amounts. Stage 1 needs the
# network and a few minutes; stage 2 is CPU-bound and writes ~590 MB; stages 3-4 are
# seconds. If data/ and the scenario are already present, `bash reproduce.sh verify`
# skips straight to the claims.
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
export PYTHONPATH="$REPO/services/api:$REPO/services/api/tests"
PY="${PY:-python3}"
STAGE="${1:-all}"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }

# Fail early and legibly. Without this, a missing dependency surfaces much later as a
# pytest collection error that says nothing about the actual cause.
if ! $PY -c 'import fastapi, numpy, yaml' 2>/dev/null; then
  echo "Missing Python dependencies for '$PY'." >&2
  echo "  python3 -m venv .venv && . .venv/bin/activate" >&2
  echo "  pip install -r requirements.txt" >&2
  echo "Or point PY at an interpreter that already has them:  PY=/path/to/python bash reproduce.sh" >&2
  exit 1
fi

if [[ "$STAGE" == "all" || "$STAGE" == "data" ]]; then
  step "1/4  Raw data (network required; ~50 MB, a few minutes)"
  ( cd "$REPO/services/api/scripts"
    PYTHONPATH="$REPO/services/api/scripts" $PY fetch_raw.py
    PYTHONPATH="$REPO/services/api/scripts" $PY fetch_env.py
    PYTHONPATH="$REPO/services/api/scripts" $PY fetch_charging.py )

  step "2/4  Derived graph and gazetteer"
  ( cd "$REPO/services/api/scripts"
    for s in thuduc danang; do
      SCENE=$s PYTHONPATH="$REPO/services/api/scripts" $PY build_graph.py
      SCENE=$s PYTHONPATH="$REPO/services/api/scripts" $PY attach_terrain.py
      SCENE=$s PYTHONPATH="$REPO/services/api/scripts" $PY build_gazetteer.py
    done )
fi

if [[ "$STAGE" == "all" || "$STAGE" == "storm" ]]; then
  step "3/4  Storm scenario (CPU-bound, writes ~590 MB)"
  # Content-addressed by spec hash: the same spec and seed produce identical bytes
  # (gate G2.1), so this rebuilds rather than needing to be shipped.
  for s in thuduc danang; do SCENE=$s $PY -m app.sim.storm; done
fi

step "4/4  Tests and claim verification"
$PY -m pytest "$REPO/services/api/tests" -q
$PY verify.py
