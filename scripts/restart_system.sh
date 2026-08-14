#!/usr/bin/env bash
# Restart the complete local environment, clearing transient jobs and caches
# without deleting reports, API keys, or database volumes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${ROOT}/docker-compose.yml"

fail() {
    printf '[ERROR] %s\n' "$1" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || fail "Docker is required."
docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop and retry."

printf '[INFO] Clearing queued and in-flight analysis jobs from Redis...\n'
if docker compose -f "${COMPOSE_FILE}" ps --status running --services 2>/dev/null \
    | grep -qx 'redis'; then
    docker compose -f "${COMPOSE_FILE}" exec -T redis redis-cli FLUSHDB >/dev/null
else
    printf '[INFO] Redis is not running; there are no live queued jobs to clear.\n'
fi

printf '[INFO] Stopping the Compose platform (persistent volumes are kept)...\n'
docker compose -f "${COMPOSE_FILE}" down --remove-orphans

printf '[INFO] Removing transient application caches...\n'
shopt -s nullglob
rm -rf \
    "${ROOT}/frontend/.next" \
    "${ROOT}/.pytest_cache" \
    "${ROOT}/.ruff_cache" \
    "${ROOT}/services/llm/.pytest_cache" \
    "${ROOT}/services/orchestrator/.pytest_cache" \
    "${ROOT}/services"/*/__pycache__ \
    "${ROOT}/services"/*/tests/__pycache__ \
    "${ROOT}/tests/__pycache__"
shopt -u nullglob

printf '[INFO] Resetting the demo workload to clear any injected fault scenario...\n'
for res in deployment/demo-app service/demo-app-svc configmap/demo-config; do
    kubectl delete "${res}" -n demo --ignore-not-found >/dev/null 2>&1 || true
done

printf '[INFO] Starting minikube, the demo workload, and the Compose platform...\n'
bash "${ROOT}/scripts/start_local.sh"

printf '[INFO] Waiting for Redis to become healthy before flushing the queue...\n'
for _ in $(seq 1 30); do
    if docker compose -f "${COMPOSE_FILE}" exec -T redis redis-cli PING \
        >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
docker compose -f "${COMPOSE_FILE}" exec -T redis redis-cli FLUSHDB >/dev/null \
    || printf '[WARN] Could not flush Redis; the queue/state from the previous run may persist.\n' >&2
printf '[INFO] Restart complete. Reports, SQLite data, and API keys were preserved.\n'
