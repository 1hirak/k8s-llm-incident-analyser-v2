#!/usr/bin/env bash
# Restart the complete local environment without deleting persistent data.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${ROOT}/docker-compose.yml"

fail() {
    printf '[ERROR] %s\n' "$1" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || fail "Docker is required."
docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop and retry."

printf '[INFO] Stopping the Compose platform (persistent volumes are kept)...\n'
docker compose -f "${COMPOSE_FILE}" down

printf '[INFO] Starting minikube, the demo workload, and the Compose platform...\n'
bash "${ROOT}/scripts/start_local.sh"
