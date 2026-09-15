#!/usr/bin/env bash
# Generate the TS client types from openapi.yaml (deterministic).
# Python side uses hand-written pydantic models validated by contract tests
# against this same file (DECISIONS.md entry 002).
set -euo pipefail
cd "$(dirname "$0")"
npx --yes openapi-typescript@7 openapi.yaml -o ../../apps/web/src/api/types.gen.ts
