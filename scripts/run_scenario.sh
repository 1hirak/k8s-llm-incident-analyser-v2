#!/usr/bin/env bash
set -euo pipefail

SCENARIO_DIR="k8s/scenarios"
BASE_DIR="k8s/base"
NAMESPACE="demo"

usage() {
    echo "Usage: $0 <scenario-number|scenario-name|all|reset>"
    echo ""
    echo "Examples:"
    echo "  $0 01            # Apply scenario 01"
    echo "  $0 01-missing-env"
    echo "  $0 all            # Run all scenarios sequentially"
    echo "  $0 reset           # Tear down and re-apply base only"
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

TARGET="$1"

ensure_cluster() {
    if ! kubectl cluster-info >/dev/null 2>&1; then
        echo "[ERROR] kubectl cannot reach a cluster."
        echo "  Start Minikube:  minikube start"
        echo "  Or install k3s:  curl -sfL https://get.k3s.io | sh -"
        exit 1
    fi
}

apply_base() {
    echo "[INFO] Applying base manifests from ${BASE_DIR}"
    kubectl apply -f "${BASE_DIR}/namespace.yaml"
    kubectl apply -f "${BASE_DIR}/configmap.yaml"
    kubectl apply -f "${BASE_DIR}/deployment.yaml"
    kubectl apply -f "${BASE_DIR}/service.yaml"
}

reset_base() {
    echo "[INFO] Resetting to healthy baseline"
    kubectl delete deployment demo-app -n "${NAMESPACE}" 2>/dev/null || true
    kubectl delete service demo-app -n "${NAMESPACE}" 2>/dev/null || true
    kubectl delete configmap demo-config -n "${NAMESPACE}" 2>/dev/null || true
    kubectl delete namespace "${NAMESPACE}" 2>/dev/null || true
    sleep 2
    apply_base
    echo "[INFO] Waiting for demo-app pod to be ready..."
    kubectl rollout status deployment/demo-app -n "${NAMESPACE}" --timeout=120s
}

apply_scenario() {
    local name="$1"
    local path="${SCENARIO_DIR}/${name}"
    if [[ ! -f "${path}/fault.yaml" ]]; then
        echo "[ERROR] Scenario fault.yaml not found at ${path}/fault.yaml"
        exit 1
    fi
    echo "[INFO] Applying scenario: ${name}"
    local kind resource_name kind_lower
    kind=$(grep '^kind:' "${path}/fault.yaml" | awk '{print $2}')
    resource_name=$(grep '  name:' "${path}/fault.yaml" | head -1 | awk '{print $2}')
    kind_lower=$(echo "${kind}" | tr '[:upper:]' '[:lower:]')
    kubectl patch "${kind_lower}/${resource_name}" -n "${NAMESPACE}" \
        --type strategic -p "$(cat "${path}/fault.yaml")"
    echo "[INFO] Scenario applied. Pod state will change shortly."
    echo "       Run 'kubectl get pods -n ${NAMESPACE} -w' to observe."
    echo "       Trigger analysis with:"
    echo "       curl -X POST http://localhost:8000/api/jobs \\"
    echo "         -H 'Content-Type: application/json' \\"
    echo "         -d '{\"namespace\": \"${NAMESPACE}\", \"pod_name\": \"demo-app\"}'"
    echo "       Then watch live progress in the dashboard: http://localhost:3000/analyse"
}

resolve_scenario() {
    local input="$1"
    if [[ -d "${SCENARIO_DIR}/${input}" ]]; then
        echo "${input}"
        return
    fi
    local padded
    padded=$(printf "%02d" "${input}" 2>/dev/null || true)
    if [[ -n "${padded}" ]]; then
        local match
        match=$(ls -d "${SCENARIO_DIR}/${padded}-"* 2>/dev/null | head -1 || true)
        if [[ -n "${match}" ]]; then
            echo "${match}" | sed "s|${SCENARIO_DIR}/||"
            return
        fi
    fi
    echo ""
}

main() {
    ensure_cluster
    if [[ "${TARGET}" == "reset" ]]; then
        reset_base
        return
    fi
    if [[ "${TARGET}" == "all" ]]; then
        for dir in "${SCENARIO_DIR}"/*/; do
            local name
            name=$(basename "${dir}")
            echo "=== ${name} ==="
            reset_base
            sleep 3
            apply_scenario "${name}"
            echo "=== Press Enter to continue, Ctrl-C to stop ==="
            read -r || break
        done
        return
    fi
    local resolved
    resolved=$(resolve_scenario "${TARGET}")
    if [[ -z "${resolved}" ]]; then
        echo "[ERROR] Could not resolve scenario: ${TARGET}"
        echo "[INFO] Available scenarios:"
        ls -1 "${SCENARIO_DIR}" | sed 's/^/  /'
        exit 1
    fi
    apply_base
    sleep 2
    apply_scenario "${resolved}"
}

main
