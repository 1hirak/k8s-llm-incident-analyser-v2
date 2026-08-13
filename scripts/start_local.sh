#!/usr/bin/env bash
# Start the complete local environment: minikube target cluster + Compose platform.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${MINIKUBE_PROFILE:-minikube}"
DRIVER="${MINIKUBE_DRIVER:-docker}"
RUNTIME_DIR="${ROOT}/.runtime"
RUNTIME_KUBECONFIG="${RUNTIME_DIR}/kubeconfig"

info() { printf '[INFO] %s\n' "$1"; }
fail() { printf '[ERROR] %s\n' "$1" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker is required."
command -v minikube >/dev/null 2>&1 || fail "Minikube is required. Install it before starting the stack."
command -v kubectl >/dev/null 2>&1 || fail "kubectl is required."

if ! docker info >/dev/null 2>&1; then
    fail "Docker is not running. Start Docker Desktop and retry."
fi

STATUS="$(minikube status --profile "${PROFILE}" 2>/dev/null || true)"
if ! printf '%s\n' "${STATUS}" | grep -qi 'host: running'; then
    info "Starting minikube profile '${PROFILE}' with the ${DRIVER} driver..."
    minikube start --profile "${PROFILE}" --driver="${DRIVER}"
else
    info "Minikube profile '${PROFILE}' is already running."
fi

kubectl config use-context "${PROFILE}" >/dev/null

mkdir -p "${RUNTIME_DIR}"
kubectl config view --minify --raw --flatten > "${RUNTIME_KUBECONFIG}"
SERVER="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
if [[ "${SERVER}" == https://127.0.0.1:* || "${SERVER}" == https://localhost:* ]]; then
    PORT="${SERVER##*:}"
    TMP_KUBECONFIG="${RUNTIME_KUBECONFIG}.tmp"
    sed "s|${SERVER}|https://control-plane.minikube.internal:${PORT}|" \
        "${RUNTIME_KUBECONFIG}" > "${TMP_KUBECONFIG}"
    mv "${TMP_KUBECONFIG}" "${RUNTIME_KUBECONFIG}"
fi
chmod 600 "${RUNTIME_KUBECONFIG}"
info "Prepared a container-compatible kubeconfig for ${SERVER}."

info "Building demo-app into minikube..."
minikube image build --profile "${PROFILE}" -t demo-app:latest "${ROOT}/demo-app"
minikube image ls --profile "${PROFILE}" | grep -q 'docker.io/library/demo-app:latest' \
    || fail "demo-app image was not loaded into minikube."

info "Applying the demo workload..."
kubectl apply -f "${ROOT}/k8s/base/namespace.yaml"
kubectl wait --for=jsonpath='{.status.phase}'=Active namespace/demo --timeout=60s
kubectl apply -f "${ROOT}/k8s/base/configmap.yaml"
kubectl apply -f "${ROOT}/k8s/base/deployment.yaml"
kubectl apply -f "${ROOT}/k8s/base/service.yaml"
kubectl rollout status deployment/demo-app -n demo --timeout=180s

if [[ "${SKIP_COMPOSE:-false}" == "true" ]]; then
    info "Minikube is ready; skipping the Compose platform startup."
    exit 0
fi

info "Starting the Compose platform..."
docker compose -f "${ROOT}/docker-compose.yml" up --build -d

cat <<EOF

Local environment is ready:
  Dashboard: http://localhost:3000
  Gateway:   http://localhost:8000
  Cluster:   minikube profile '${PROFILE}'
EOF
