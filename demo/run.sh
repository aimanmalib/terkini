#!/usr/bin/env bash
# One-command demo: the replay page and the HTTP API from a clean clone. Needs Docker only; no API key.
#
#   demo/run.sh          start, wait until it answers, print the URL and a short guide
#   demo/run.sh stop     remove the container
#
# It runs the official uv image (pinned by digest) with this folder mounted read-only, installs the locked
# dependencies inside the container and starts `terkini serve` in replay mode. Nothing is written to this folder.
# If anything fails, the container is removed before the script exits.
set -euo pipefail

IMAGE="ghcr.io/astral-sh/uv@sha256:4677e08839853fe91c523b593f822ec1e87c7b91ba4c6b30929016b2e0933cd5" # 0.12.5-python3.12-trixie-slim
NAME="${TERKINI_DEMO_NAME:-terkini-demo}"
FIRST_PORT="${TERKINI_DEMO_PORT:-8710}"
WAIT_SECONDS="${TERKINI_DEMO_WAIT:-180}"
CASE="my-12-kimi-k3-1-pro"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

remove() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }

if [ "${1:-}" = "stop" ]; then
  remove
  echo "Removed $NAME."
  exit 0
fi

command -v docker >/dev/null || { echo "Docker is needed: https://docs.docker.com/get-docker/" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is installed but not running." >&2; exit 1; }

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
PORT="$FIRST_PORT"
while port_busy "$PORT"; do
  PORT=$((PORT + 1))
  [ "$PORT" -lt $((FIRST_PORT + 50)) ] || { echo "No free port from $FIRST_PORT to $PORT." >&2; exit 1; }
done

remove
trap 'status=$?; if [ "$status" -ne 0 ]; then echo "Demo failed; last log lines:" >&2; docker logs --tail 20 "$NAME" >&2 2>/dev/null || true; remove; fi' EXIT

echo "Starting $NAME on port $PORT (it installs the locked Python packages first; this can take a minute)..."
docker run -d --name "$NAME" --cpus 1 --memory 768m \
  -p "127.0.0.1:$PORT:8710" \
  -v "$ROOT:/src:ro" -w /src \
  -e UV_PROJECT_ENVIRONMENT=/opt/venv -e UV_CACHE_DIR=/tmp/uv-cache -e UV_LINK_MODE=copy \
  -e TAVILY_API_KEY= \
  --tmpfs /tmp:exec \
  "$IMAGE" \
  sh -c 'uv sync --frozen --no-dev --quiet && exec /opt/venv/bin/terkini serve --host 0.0.0.0 --port 8710' \
  >/dev/null

deadline=$(( $(date +%s) + WAIT_SECONDS ))
until docker exec "$NAME" /opt/venv/bin/python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8710/healthz', timeout=2)" >/dev/null 2>&1; do
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ] || { echo "The container stopped." >&2; exit 1; }
  [ "$(date +%s)" -lt "$deadline" ] || { echo "Not ready after ${WAIT_SECONDS}s." >&2; exit 1; }
  sleep 2
done

echo
docker exec "$NAME" /opt/venv/bin/terkini check --pack my --case "$CASE"
cat <<EOF

Terkini is running in replay mode (recorded runs from 20 and 21 Nov 2026, no key needed).

  Page:  http://127.0.0.1:$PORT/
         Pick a recorded run. Red claims are outdated against an official page; open a card to see the exact quote.
         The language switch is at the top right (English, Bahasa Melayu).
  API:   curl -s http://127.0.0.1:$PORT/api/check -H 'content-type: application/json' \\
           -d '{"pack": "my", "case": "$CASE"}'
  Stop:  demo/run.sh stop
EOF
