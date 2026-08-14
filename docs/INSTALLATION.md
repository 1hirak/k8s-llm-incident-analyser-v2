# Installation

This project has two different deployment modes. The Minikube path is a
development demo. The external-cluster path is the production-oriented path
when the analyser runs in a container and diagnoses another Kubernetes cluster.

## What Runs Where

The analyser container does not magically see another cluster. It needs:

- Network access from the container to the target cluster's Kubernetes API.
- A kubeconfig mounted read-only into the collector, watcher, and remediation
  containers.
- A Kubernetes identity with read permissions for collection and separate,
  explicitly approved patch permissions for remediation.
- Outbound HTTPS access from `llm-svc` to the selected LLM provider, unless the
  mock provider or a private LLM endpoint is used.

The data path is:

```text
watcher -> orchestrator -> collector -> processor -> llm -> reports
                         collector -> target kube-apiserver (read)
                         remediation -> target kube-apiserver (approved patch)
```

The LLM receives only the processor's filtered and redacted evidence. It does
not receive the mounted kubeconfig or Kubernetes token.

## External Cluster With Docker Compose

### 1. Prerequisites

- Docker Engine with Compose v2.24 or newer
- `kubectl` on the installation host
- A target Kubernetes cluster whose API endpoint is reachable from Docker
- A registry/LLM API key if `LLM_PROVIDER` is not `mock`

The target cluster does not need to run the analyser. The analyser may run on a
VM, laptop, bastion host, or separate container platform.

### 2. Create a dedicated target-cluster identity

Run the following with an administrator kubeconfig. The generated runtime
kubeconfig uses a short-lived ServiceAccount token and is not copied into an
image:

```bash
./scripts/create_external_kubeconfig.sh \
  --output "$PWD/.runtime/external-kubeconfig" \
  --namespaces production,staging \
  --remediation
```

The script creates read-only Roles in the selected namespaces. With
`--remediation`, it creates a second ServiceAccount and kubeconfig with only
`get` and `patch` on Deployments plus rollout verification reads. The collector
and watcher use the first kubeconfig; remediation uses the generated
`.remediation` kubeconfig. Do not use an administrator kubeconfig for the
Compose services.

The token expires after 24 hours. Re-run the script as part of credential
rotation and restart the Compose stack. If the cluster uses a cloud exec plugin,
either provide a kubeconfig using a credential mechanism available inside the
image or use a dedicated token/certificate kubeconfig; host-only `aws`, `az`,
or `gcloud` binaries are not available inside these images.

### 3. Configure the analyser

```bash
cp .env.external.example .env.external
```

Set at least:

```dotenv
KUBECONFIG_FILE=/absolute/path/to/.runtime/external-kubeconfig
REMEDIATION_KUBECONFIG_FILE=/absolute/path/to/.runtime/external-kubeconfig.remediation
WATCH_NAMESPACES=production,staging
REMEDIATION_NAMESPACES=production,staging
REMEDIATION_ENABLED=true
REMEDIATION_MODE=approval
GATEWAY_API_TOKEN=generate-a-long-random-value
NEXT_PUBLIC_API_URL=http://localhost:8000
```

`WATCH_NAMESPACES` and `REMEDIATION_NAMESPACES` are application-level
allowlists. Kubernetes RBAC is the enforcement boundary and must be at least
as restrictive as these values.

### 4. Start and verify

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.external.yml \
  --env-file .env.external \
  up --build -d

curl http://localhost:8000/health
curl -H "Authorization: Bearer ${GATEWAY_API_TOKEN}" \
  "http://localhost:8000/api/cluster/status?namespace=production"
curl -H "Authorization: Bearer ${GATEWAY_API_TOKEN}" \
  http://localhost:8000/api/targets?kind=Pod\&namespace=production
```

The external overlay does not start the bundled demo workload or scenario
service. It keeps Redis and internal services private and publishes only the
frontend and gateway.

The watcher scans every `WATCH_INTERVAL_SECONDS` and submits normal analysis
jobs for unhealthy pods. It deduplicates the same namespace/pod/failure
signature for `WATCH_COOLDOWN_SECONDS`. A manual job remains available:

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Authorization: Bearer ${GATEWAY_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"namespace":"production","pod_name":"payments-api"}'
```

## Approved Remediation

Remediation is disabled by default in the base Compose and Kubernetes
manifests. When enabled, it is still approval-gated:

1. A diagnosis may contain a typed action such as changing Deployment
   resources, changing an image, changing a probe path, or restarting a
   Deployment.
2. `POST /api/remediations` performs a Kubernetes server-side dry-run and
   stores the proposal in Redis.
3. An authenticated operator reviews the returned dry-run output.
4. `POST /api/remediations/{id}/approve` with `confirm: true` applies the typed
   patch and waits for rollout status.
5. The resulting record contains the approver, status, output, and error if the
   rollout failed.

The service never executes `recommended_commands` from the LLM. Those strings
remain copyable operator guidance. A typed action is validated against the
allowed namespaces and action types before `kubectl` is called.

Example API flow:

```bash
proposal=$(curl -sS -X POST http://localhost:8000/api/remediations \
  -H "Authorization: Bearer ${GATEWAY_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  -H 'X-Operator-Id: alice' \
  -d '{
    "action": {
      "action_type": "set_deployment_resources",
      "namespace": "production",
      "deployment_name": "payments-api",
      "container_name": "payments-api",
      "memory_limit": "512Mi"
    }
  }')

remediation_id=$(printf '%s' "$proposal" | jq -r .remediation_id)
curl -sS -X POST "http://localhost:8000/api/remediations/${remediation_id}/approve" \
  -H "Authorization: Bearer ${GATEWAY_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  -H 'X-Operator-Id: alice' \
  -d '{"confirm":true}'
```

Do not set remediation namespaces to `*` in production. Add one RoleBinding
per approved target namespace instead.

## In-Cluster Deployment

The manifests under `k8s/services/` run the analyser inside an `analyser`
namespace. The collector and watcher use the projected ServiceAccount token
and CA automatically. The remediation ServiceAccount is bound only to the
`demo` namespace in the sample manifests.

```bash
kubectl apply -f k8s/services/namespace.yaml
kubectl apply -f k8s/services/rbac-collector.yaml
kubectl apply -f k8s/services/rbac-remediation.yaml
kubectl apply -f k8s/services/rbac-scenario.yaml       # demo testing only
kubectl apply -f k8s/services/redis.yaml
kubectl apply -f k8s/services/collector.yaml
kubectl apply -f k8s/services/watcher.yaml
kubectl apply -f k8s/services/remediation.yaml
kubectl apply -f k8s/services/processor.yaml
kubectl apply -f k8s/services/llm.yaml
kubectl apply -f k8s/services/reports.yaml
kubectl apply -f k8s/services/orchestrator.yaml
kubectl apply -f k8s/services/gateway.yaml
kubectl apply -f k8s/services/frontend.yaml
```

For a real deployment, use registry-qualified immutable image tags, create the
`llm-secrets` Secret, create a `gateway-auth` Secret containing `API_TOKEN`
(for example, `kubectl -n analyser create secret generic gateway-auth --from-literal=API_TOKEN="$GATEWAY_API_TOKEN"`), set
`REMEDIATION_ENABLED=true` only after reviewing the target RoleBindings, and
configure TLS/OIDC or an API gateway in front of the NodePort/Ingress.

The sample manifests are intentionally not a complete production hardening
profile. Add NetworkPolicies, non-root security contexts, image pull secrets,
restricted Pod Security, persistent storage suitable for the environment, and
backups before production use.

## Development Demo

The original local path remains available:

```bash
make up
open http://localhost:3000
```

This starts Minikube, deploys `demo-app`, generates `.runtime/kubeconfig`, and
runs the demo scenario service. It is useful for tests and evaluation, not for
accessing a customer's cluster.
