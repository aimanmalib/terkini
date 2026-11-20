#!/usr/bin/env bash
# Fast quality gate: sync locked dependencies, then run the unit tests offline against recorded fixtures.
set -euo pipefail

# Git hooks export GIT_DIR and friends; tests that run git in temp folders must not inherit them.
while IFS= read -r v; do unset "$v"; done < <(env | grep -o '^GIT_[A-Z_]*' || true)

cd "$(dirname "$0")/.."
started=$(date +%s)

uv sync --frozen --quiet
# Tests never touch the network; make an accidental live call fail loudly instead of spending credits.
TAVILY_API_KEY="" uv run --frozen pytest -p no:cacheprovider

echo "gate: OK in $(( $(date +%s) - started ))s"
