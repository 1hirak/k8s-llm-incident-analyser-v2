#!/usr/bin/env bash
set -euo pipefail

# Create a short-lived, least-privilege kubeconfig for the external Compose
# deployment. Run this with an administrator kubeconfig, then remove the
# administrator credentials from the host process/environment.

NAMESPACE="analyser"
SERVICE_ACCOUNT="analyser-agent"
REMEDIATION_SERVICE_ACCOUNT="analyser-remediator"
TARGET_NAMESPACES="demo"
OUTPUT=""
REMEDIATION_OUTPUT=""
REMEDIATION="false"

usage() {
    cat <<'EOF'
Usage: create_external_kubeconfig.sh --output PATH [options]

Options:
  --output PATH          kubeconfig output path (required)
  --namespaces LIST     comma-separated target namespaces (default: demo)
  --service-account NAME collector ServiceAccount name (default: analyser-agent)
  --namespace NAME      namespace for the ServiceAccount (default: analyser)
  --remediation         also create a separate remediation identity
  --remediation-output PATH remediation kubeconfig (default: PATH.remediation)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output) OUTPUT="${2:?missing value for --output}"; shift 2 ;;
        --namespaces) TARGET_NAMESPACES="${2:?missing value for --namespaces}"; shift 2 ;;
        --service-account) SERVICE_ACCOUNT="${2:?missing value for --service-account}"; shift 2 ;;
        --namespace) NAMESPACE="${2:?missing value for --namespace}"; shift 2 ;;
        --remediation-output) REMEDIATION_OUTPUT="${2:?missing value for --remediation-output}"; shift 2 ;;
        --remediation) REMEDIATION="true"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

[[ -n "${OUTPUT}" ]] || { usage >&2; exit 2; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 1; }

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"
kubectl create serviceaccount "${SERVICE_ACCOUNT}" -n "${NAMESPACE}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
if [[ "${REMEDIATION}" == "true" ]]; then
    REMEDIATION_OUTPUT="${REMEDIATION_OUTPUT:-${OUTPUT}.remediation}"
    kubectl create serviceaccount "${REMEDIATION_SERVICE_ACCOUNT}" -n "${NAMESPACE}" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
fi

IFS=',' read -r -a namespaces <<< "${TARGET_NAMESPACES}"
for target in "${namespaces[@]}"; do
    [[ -n "${target}" ]] || continue
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: analyser-collector
  namespace: ${target}
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log", "events", "services"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["batch"]
  resources: ["jobs", "cronjobs"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: analyser-collector
  namespace: ${target}
subjects:
- kind: ServiceAccount
  name: ${SERVICE_ACCOUNT}
  namespace: ${NAMESPACE}
roleRef:
  kind: Role
  name: analyser-collector
  apiGroup: rbac.authorization.k8s.io
EOF

    if [[ "${REMEDIATION}" == "true" ]]; then
        kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: analyser-remediator
  namespace: ${target}
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "patch"]
- apiGroups: ["apps"]
  resources: ["deployments/status", "replicasets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: analyser-remediator
  namespace: ${target}
subjects:
- kind: ServiceAccount
  name: ${REMEDIATION_SERVICE_ACCOUNT}
  namespace: ${NAMESPACE}
roleRef:
  kind: Role
  name: analyser-remediator
  apiGroup: rbac.authorization.k8s.io
EOF
    fi
done

SERVER="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
CA_DATA="$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"

create_kubeconfig() {
    local service_account="$1"
    local output="$2"
    local token
    token="$(kubectl create token "${service_account}" -n "${NAMESPACE}" --duration=24h)"
    mkdir -p "$(dirname "${output}")"
    kubectl config --kubeconfig "${output}" unset current-context >/dev/null 2>&1 || true
    kubectl config --kubeconfig "${output}" set-cluster target \
        --server="${SERVER}" --certificate-authority-data="${CA_DATA}" >/dev/null
    kubectl config --kubeconfig "${output}" set-credentials "${service_account}" \
        --token="${token}" >/dev/null
    kubectl config --kubeconfig "${output}" set-context target \
        --cluster=target --user="${service_account}" >/dev/null
    kubectl config --kubeconfig "${output}" use-context target >/dev/null
    chmod 600 "${output}"
}

create_kubeconfig "${SERVICE_ACCOUNT}" "${OUTPUT}"
if [[ "${REMEDIATION}" == "true" ]]; then
    create_kubeconfig "${REMEDIATION_SERVICE_ACCOUNT}" "${REMEDIATION_OUTPUT}"
fi

echo "Created ${OUTPUT} for ${SERVICE_ACCOUNT}; token expires after 24 hours."
echo "Target namespaces: ${TARGET_NAMESPACES}"
echo "Remediation permissions: ${REMEDIATION}"
if [[ "${REMEDIATION}" == "true" ]]; then
    echo "Created ${REMEDIATION_OUTPUT} for ${REMEDIATION_SERVICE_ACCOUNT}."
fi
echo "Verify with: KUBECONFIG=${OUTPUT} kubectl auth can-i get pods -n ${namespaces[0]}"
