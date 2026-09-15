#!/usr/bin/env bash
# Assemble a self-contained bundle: this folder plus a snapshot of the source.
#
# The source is copied at pack time rather than committed into artifact/, because a
# second copy in git drifts from the first the moment anyone edits the original. The
# bundle records the commit it came from so a reviewer can always diff it back.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
OUT="${1:-code}"

rm -rf "$OUT" && mkdir -p "$OUT"

# Everything needed to *run* the system, not just to read it. An earlier version copied
# only apps/web/src and package.json, which is enough to inspect the client and not
# enough to start it -- index.html and vite.config.ts were missing, so the bundle looked
# complete and was not. The companion documents come too, so the README's links resolve.
for p in services/api config packages/contracts docs \
         Makefile docker-compose.yml .env.example \
         proposal.tex proposal.pdf technical.tex technical.pdf; do
  [ -e "$REPO/$p" ] || continue
  mkdir -p "$OUT/$(dirname "$p")"
  cp -R "$REPO/$p" "$OUT/$p"
done

mkdir -p "$OUT/apps"
cp -R "$REPO/apps/web" "$OUT/apps/web"
rm -rf "$OUT/apps/web/node_modules" "$OUT/apps/web/dist" \
       "$OUT/apps/web/tsconfig.tsbuildinfo" "$OUT/apps/web/e2e/shots"
find "$OUT" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '*.pyc' -delete 2>/dev/null || true
find "$OUT" -name '.DS_Store' -delete 2>/dev/null || true
# Prune empty directories, repeatedly: removing caches can leave a parent holding
# nothing, and that parent's parent in turn. A bundle handed to a reviewer should not
# contain folders that explain nothing.
while [ -n "$(find "$OUT" -type d -empty -print -quit)" ]; do
  find "$OUT" -type d -empty -delete 2>/dev/null || break
done

{
  echo "commit:  $(cd "$REPO" && git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "branch:  $(cd "$REPO" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  echo "dirty:   $(cd "$REPO" && [ -n "$(git status --porcelain)" ] && echo yes || echo no)"
  echo "packed:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$OUT/PROVENANCE"

# Refuse to hand out a bundle containing anything key-shaped. Placeholders used by the
# tests are matched too and then filtered by exact value, so a real key cannot hide behind
# "it is probably just a fixture".
KNOWN_PLACEHOLDERS='sk-test-not-real|sk-ant-api03-A+$|sk-proj-B+$|AIzaC+$'
LEAKS=$(grep -rhoaE 'sk-ant-[A-Za-z0-9_-]{16,}|sk-proj-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9]{32,}|AIza[A-Za-z0-9_-]{30,}' "$OUT" . 2>/dev/null \
        | sort -u | grep -vE "$KNOWN_PLACEHOLDERS" || true)
if [ -n "$LEAKS" ]; then
  echo "REFUSING TO PACK: credential-shaped strings found in the bundle:" >&2
  echo "$LEAKS" | sed 's/\(.\{12\}\).*/\1.../' >&2
  echo "Remove them before shipping. This artifact carries no keys by design." >&2
  rm -rf "$OUT"
  exit 1
fi

echo "packed $(du -sh "$OUT" | cut -f1) into $OUT/ (see $OUT/PROVENANCE)"
echo "secret scan: clean - no credential-shaped strings in the bundle"
