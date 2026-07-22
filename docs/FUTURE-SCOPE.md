# Future Scope — K8s LLM Incident Analyser on Production Kubernetes

> Diagrams use **Mermaid** syntax. Renders natively on GitHub, GitLab, Azure DevOps, and in any VS Code Markdown preview with the Mermaid extension.

---

## 1. Where This Fits Inside Your Existing K8s Cluster

This tool deploys as **one extra namespace** (`analyser`) with RBAC-scoped access to read pod logs and optionally inject faults in a test namespace. It does not replace your monitoring — it sits **downstream of alerts** and provides automated root-cause diagnosis via an LLM.

```mermaid
graph TB
    subgraph CLUSTER["☸️ YOUR KUBERNETES CLUSTER"]
        direction TB

        subgraph APPS["YOUR APPS (prod, staging, etc.)"]
            orders["orders-api"]
            payments["payments-svc"]
            users["user-service"]
        end

        subgraph ANALYSER["🆕 analyser namespace ← THIS TOOL"]
            direction TB
            frontend["frontend :3000<br/>Dashboard"]
            gateway["gateway :8000<br/>REST + SSE API"]
            orch["orchestrator :8001<br/>job coordinator"]
            coll["collector :8002<br/>kubectl evidence"]
            proc["processor :8003<br/>redaction + filter"]
            llm["llm :8004<br/>OpenAI / Anthropic"]
            reports["reports :8005<br/>PostgreSQL"]
            scenario["scenario :8006<br/>fault injection"]
            redis[("Redis<br/>job state + queue")]

            gateway --> orch
            orch --> coll
            orch --> proc
            orch --> llm
            orch --> reports
            orch <--> redis
            reports --> pg[("PostgreSQL")]
        end

        subgraph MONITORING["monitoring namespace"]
            prom["Prometheus"]
            grafana["Grafana"]
            loki["Loki"]
        end

        frontend --> gateway
    end

    coll -.->|"🔍 kubectl logs/describe (READ)"| orders
    coll -.->|"🔍 kubectl logs/describe (READ)"| payments
    scenario -.->|"🔧 kubectl patch (demo ns only)"| APPS
    llm -.->|"🔗 HTTPS"| ext["☁️ api.openai.com"]
```

**RBAC boundary:**

```mermaid
graph LR
    subgraph ANALYSER["analyser namespace"]
        collector["collector-sa"]
        scenario["scenario-sa"]
    end

    subgraph TARGET["target namespaces"]
        prod["prod"]
        staging["staging"]
        demo["demo"]
    end

    collector -->|"ClusterRole<br/>✓ pods, pods/log, events<br/>✓ get, list, watch<br/>✗ write ✗ delete"| prod
    collector -->|"same ClusterRole"| staging
    scenario -->|"Role (demo ns only)<br/>✓ deployments<br/>✓ configmaps<br/>✓ patch, update"| demo
```

---

## 2. End-to-End Incident Lifecycle

```mermaid
sequenceDiagram
    participant Alert as 🚨 PagerDuty / Alertmanager
    participant Gateway as Gateway API
    participant Orch as Orchestrator
    participant Redis as Redis
    participant Coll as Collector
    participant Proc as Processor
    participant LLM as LLM Service
    participant Rep as Reports
    participant Slack as 💬 Slack / Teams

    Alert->>Gateway: POST /api/jobs {namespace, pod_name}
    Gateway->>Orch: Forward job request
    Orch->>Redis: HSET job:{id} status=queued
    Note over Orch,Redis: Stage: ⬜ queued

    Orch->>Coll: Collect evidence
    Coll->>Coll: kubectl logs, describe, events
    Coll-->>Orch: Raw evidence
    Orch->>Redis: HSET status=collecting
    Note over Orch,Redis: Stage: 📥 collecting

    Orch->>Proc: Preprocess evidence
    Proc->>Proc: Redact secrets, filter noise
    Proc-->>Orch: Cleaned evidence
    Orch->>Redis: HSET status=processing
    Note over Orch,Redis: Stage: 🔧 processing

    Orch->>LLM: Analyse (JSON schema)
    LLM->>LLM: Call OpenAI / Anthropic
    LLM-->>Orch: IncidentReport {root_cause, evidence, fix}
    Orch->>Redis: HSET status=llm_call
    Note over Orch,Redis: Stage: 🤖 llm_call

    Orch->>Rep: Persist report
    Rep->>Rep: INSERT INTO incidents
    Rep-->>Orch: Done
    Orch->>Redis: HSET status=done
    Note over Orch,Redis: Stage: ✅ done

    Orch-->>Gateway: SSE: stage events + final report
    Gateway-->>Slack: 🚨 orders-api CrashLoopBackOff<br/>Root cause: OOMKilled — memory too low<br/>Fix: kubectl set resources --limits=256Mi
```

---

## 3. Platform Architecture Diagrams

### 3.1 AWS EKS

```mermaid
graph TB
    subgraph INTERNET["🌐 Internet"]
        user["👤 User Browser"]
        pd["🚨 PagerDuty"]
    end

    subgraph AWS["☁️ AWS Account"]
        route53["Route53<br/>incidents.company.com"]
        acm["ACM<br/>TLS cert"]
        waf["WAF"]
        alb["Application Load Balancer<br/>L7 routing + OIDC auth"]

        route53 --> alb
        acm --> alb
        waf --> alb

        subgraph EKS["☸️ EKS Cluster"]
            direction TB

            subgraph INGRESS["AWS Load Balancer Controller"]
                ing["Ingress rules"]
            end

            subgraph ANALYSER["analyser namespace"]
                f["frontend :3000"]
                gw["gateway :8000"]
                o["orchestrator :8001"]
                co["collector :8002"]
                pr["processor :8003"]
                l["llm :8004"]
                re["reports :8005"]
                sc["scenario :8006"]
                r[("redis")]
            end

            subgraph MON["monitoring namespace"]
                prom["CloudWatch + AMP"]
                graf["Managed Grafana"]
            end

            alb --> ing
            ing --> f
            ing --> gw
            gw --> o
            o --> co
            o --> pr
            o --> l
            o --> re
            o <--> r
        end

        subgraph MANAGED["AWS Managed Services"]
            rds["RDS PostgreSQL<br/>Multi-AZ · auto-backup"]
            secrets["Secrets Manager<br/>LLM API keys via IRSA"]
            ecr["ECR<br/>container images"]
            xray["X-Ray<br/>distributed tracing"]
        end

        co -.->|"kubectl READ"| EKS
        l -->|"HTTPS"| ext["api.openai.com"]
        re --> rds
        l --> secrets
    end

    user --> alb
    pd --> alb
```

**EKS: What lives WHERE**

| Component | AWS Service |
|---|---|
| Dashboard | EKS pod → ALB target |
| Gateway API | EKS pod → ALB target |
| Orchestrator, Collector, Processor, LLM, Reports, Scenario | EKS pods, ClusterIP only |
| PostgreSQL | RDS (managed) or CNPG operator in-cluster |
| Redis | ElastiCache (managed) or StatefulSet in-cluster |
| LLM API keys | Secrets Manager → IRSA → pod env |
| TLS | ACM → ALB |
| Auth | ALB + Cognito/Okta OIDC |
| Images | ECR |
| Metrics/Logs/Traces | CloudWatch + AMP + X-Ray |

---

### 3.2 Azure AKS

```mermaid
graph TB
    subgraph INTERNET["🌐 Internet"]
        user["👤 User Browser"]
        pd["🚨 PagerDuty"]
    end

    subgraph AZURE["☁️ Azure Subscription"]
        dns["Azure DNS"]
        fd["Front Door + WAF"]
        agw["Application Gateway v2<br/>(AGIC)"]

        dns --> fd --> agw

        subgraph AKS["☸️ AKS Cluster"]
            direction TB

            subgraph ANALYSER["analyser namespace"]
                f["frontend :3000"]
                gw["gateway :8000"]
                o["orchestrator :8001"]
                co["collector :8002"]
                pr["processor :8003"]
                l["llm :8004"]
                re["reports :8005"]
                sc["scenario :8006"]
                r[("redis")]
            end

            subgraph MON["observability"]
                mp["Managed Prometheus"]
                mg["Managed Grafana"]
                ci["Container Insights"]
                ai["App Insights"]
            end

            agw --> f
            agw --> gw
            gw --> o
            o --> co
            o --> pr
            o --> l
            o --> re
            o <--> r
        end

        subgraph MANAGED["Azure Managed Services"]
            pg["Azure DB for PostgreSQL<br/>Flexible · Zone-redundant HA"]
            kv["Key Vault<br/>LLM keys via CSI Driver"]
            acr["ACR · geo-replicated"]
            redis_az["Azure Cache for Redis<br/>Enterprise · Active-Active"]
        end

        co -.->|"kubectl READ"| AKS
        l -->|"HTTPS"| ext["api.openai.com"]
        re --> pg
        l -.->|"CSI volume mount"| kv
        r -.->|"or use"| redis_az
    end

    user --> fd
    pd --> fd
```

**AKS: What lives WHERE**

| Component | Azure Service |
|---|---|
| Dashboard | AKS pod → App Gateway |
| Gateway API | AKS pod → App Gateway |
| Orchestrator, Collector, Processor, LLM, Reports, Scenario | AKS pods, ClusterIP only |
| PostgreSQL | Azure DB for PostgreSQL Flexible Server |
| Redis | Azure Cache for Redis Enterprise OR in-cluster |
| LLM API keys | Key Vault → Secrets Store CSI Driver → pod volume |
| TLS | Key Vault cert → App Gateway |
| Auth | Entra ID (Azure AD) via OAuth2 Proxy |
| Images | ACR (geo-replicated) |
| Metrics/Logs/Traces | Managed Prometheus + Log Analytics + App Insights |
| Security | Defender for Containers + Azure Policy for K8s |

---

### 3.3 Custom / Self-Managed Kubernetes

```mermaid
graph TB
    subgraph INTERNET["🌐 Internet"]
        cf["Cloudflare<br/>DNS · DDoS · WAF (free)"]
    end

    cf --> lb["HAProxy / MetalLB / Nginx<br/>L4 LB · TCP 443 pass-through"]
    lb --> cluster

    subgraph cluster["☸️ Self-Managed K8s (k3s / kubeadm / RKE2)"]
        direction TB

        subgraph INGRESS["ingress-nginx + cert-manager"]
            tls["TLS · Let's Encrypt"]
            oauth["OAuth2 Proxy"]
        end

        subgraph ANALYSER["analyser namespace"]
            direction TB
            f["frontend :3000"]
            gw["gateway :8000"]
            o["orchestrator :8001"]
            co["collector :8002"]
            pr["processor :8003"]
            l["llm :8004"]
            re["reports :8005"]
            sc["scenario :8006"]
            r[("redis")]
        end

        subgraph DATA["data layer"]
            pg[("PostgreSQL<br/>CNPG · 3 replicas")]
            redis_s["Redis<br/>Sentinel · 3 replicas"]
        end

        subgraph MON["kube-prometheus-stack"]
            prom["Prometheus"]
            gf["Grafana"]
            loki["Loki"]
            tempo["Tempo"]
            am["Alertmanager"]
        end

        subgraph SEC["security"]
            vault["Vault (HA)<br/>LLM API keys"]
            kyverno["Kyverno"]
            falco["Falco"]
            trivy["Trivy Operator"]
        end

        subgraph STORAGE["Longhorn · replicated block storage"]
            pv1["Postgres PVC"]
            pv2["Redis PVC"]
        end

        INGRESS --> f
        INGRESS --> gw
        gw --> o
        o --> co
        o --> pr
        o --> l
        o --> re
        o <--> r
        re --> pg
        l -.->|"inject secrets"| vault
    end

    co -.->|"kubectl READ"| cluster
    l -->|"HTTPS"| ext["api.openai.com"]
```

**Custom K8s: What lives WHERE**

| Component | Self-Managed Solution |
|---|---|
| Cluster | k3s / kubeadm / RKE2 |
| DNS | Cloudflare (free) |
| Ingress | ingress-nginx + cert-manager + Let's Encrypt |
| Auth (dashboard) | Dex + OAuth2 Proxy (Google/GitHub/LDAP) |
| PostgreSQL | CloudNativePG operator (3-replica in-cluster) |
| Redis | Bitnami Redis Sentinel chart (3 replicas) |
| LLM API keys | HashiCorp Vault (HA) or Sealed Secrets |
| Storage | Longhorn (replicated block storage) |
| Monitoring | kube-prometheus-stack (Prometheus + Grafana + Alertmanager) |
| Logs | Loki + Promtail |
| Traces | Tempo + OpenTelemetry Collector |
| Security | Kyverno (policy), Falco (runtime), Trivy Operator (image scan) |
| GitOps | ArgoCD or Flux |
| Images | Harbor / GitLab Container Registry / GHCR |

---

## 4. Cross-Platform Component Mapping

| Component | AWS EKS | Azure AKS | Custom K8s |
|---|---|---|---|
| Kubernetes cluster | EKS (managed) | AKS (managed) | k3s / kubeadm |
| DNS | Route53 | Azure DNS | Cloudflare |
| Load Balancer | ALB | App Gateway | MetalLB / HAProxy |
| TLS certificates | ACM | Key Vault | cert-manager + LE |
| Ingress controller | AWS LB Controller | AGIC | ingress-nginx |
| Auth (OIDC/OAuth2) | ALB + Cognito | Entra ID + AGIC | Dex + OAuth2 Proxy |
| PostgreSQL | RDS | Azure DB Flex | CNPG operator |
| Redis | ElastiCache | Azure Cache | Sentinel chart |
| LLM API key storage | Secrets Mgr + IRSA | Key Vault + CSI | Vault / Sealed Secrets |
| Container registry | ECR | ACR | Harbor / GHCR |
| Metrics | CloudWatch + AMP | Managed Prometheus | kube-prometheus |
| Logs | CW Logs | Log Analytics | Loki + Promtail |
| Traces | X-Ray (ADOT) | App Insights | Tempo + OTel |
| Runtime security | GuardDuty | Defender for Containers | Falco |
| Policy enforcement | OPA / Gatekeeper | Azure Policy | Kyverno |
| Storage (PV) | EBS CSI | Azure Disk CSI | Longhorn |
| GitOps | ArgoCD / Flux | ArgoCD / Flux | ArgoCD / Flux |
| **Approx. monthly platform cost (excl. LLM)** | **~$580** | **~$1,250** | **~€55 (Hetzner)** |

---

## 5. Network Traffic Flow

```mermaid
graph TB
    subgraph EXT["🌐 External Traffic"]
        browser["👤 Browser"]
        pd["🚨 PagerDuty"]
        alert["📊 Prometheus alert"]
    end

    subgraph LB["🔀 Ingress / Load Balancer"]
        tls["TLS termination"]
    end

    subgraph ANALYSER["analyser namespace"]
        f["frontend :3000"]
        gw["gateway :8000"]
        o["orchestrator :8001"]
        co["collector :8002"]
        pr["processor :8003"]
        l["llm :8004"]
        re["reports :8005"]
        sc["scenario :8006"]
        r[("redis :6379")]
    end

    subgraph K8S_API["☸️ kube-apiserver"]
        api["API server"]
    end

    subgraph LLM_APIS["☁️ LLM Providers"]
        openai["api.openai.com"]
        anthropic["api.anthropic.com"]
    end

    browser -->|"HTTPS"| tls
    pd -->|"HTTPS"| tls
    alert -->|"HTTPS"| tls

    tls -->|"HTTP"| f
    tls -->|"HTTP"| gw

    f -->|"HTTP"| gw
    gw -->|"HTTP"| o
    gw -->|"HTTP"| re
    gw -->|"HTTP"| sc

    o -->|"HTTP"| co
    o -->|"HTTP"| pr
    o -->|"HTTP"| l
    o -->|"HTTP"| re
    o <-->|"TCP"| r

    re --> postgres[("PostgreSQL :5432")]

    co -->|"kubectl → READ pods/logs/events"| api
    sc -->|"kubectl → PATCH demo deployments"| api

    l -->|"HTTPS"| openai
    l -->|"HTTPS"| anthropic
```

---

## 6. Integration with Existing Incident Stack

```mermaid
graph TB
    subgraph SOURCES["Alert Sources"]
        am["Alertmanager"]
        pd["PagerDuty"]
        slack_in["Slack"]
        teams_in["Teams"]
    end

    subgraph ROUTER["Event Router"]
        webhook["Webhook handler"]
    end

    subgraph ANALYSER["K8s LLM Incident Analyser"]
        gateway["Gateway API<br/>POST /api/jobs"]
        pipeline["5-stage pipeline<br/>collect → process → LLM → persist"]
    end

    subgraph OUTPUTS["Output Destinations"]
        slack_out["💬 Slack message<br/>root cause + fix"]
        teams_out["💬 Teams message"]
        pd_out["🚨 PagerDuty incident<br/>enriched with analysis"]
        grafana_ann["📊 Grafana annotation"]
        jira["📋 Jira ticket<br/>auto-created"]
        dashboard["🖥️ Dashboard<br/>live SSE stream"]
    end

    am --> webhook
    pd --> webhook
    slack_in --> webhook
    teams_in --> webhook

    webhook -->|"POST /api/jobs"| gateway
    gateway --> pipeline

    pipeline --> slack_out
    pipeline --> teams_out
    pipeline --> pd_out
    pipeline --> grafana_ann
    pipeline --> jira
    pipeline --> dashboard
```

---

## 7. Daily Operational Workflows

### Workflow A: Alert-Triggered Analysis

```mermaid
sequenceDiagram
    participant Alert as 🚨 PagerDuty
    participant Gateway as Gateway API
    participant Pipeline as 5-Stage Pipeline
    participant Slack as 💬 Slack
    participant SRE as 👨‍💻 On-Call SRE

    Alert->>Gateway: POST /api/jobs {namespace, pod_name}
    Note over Alert,Gateway: orders-api in CrashLoopBackOff

    Gateway->>Pipeline: Execute pipeline
    Pipeline->>Pipeline: collecting → logs, describe, events
    Pipeline->>Pipeline: processing → redact, filter
    Pipeline->>Pipeline: llm_call → root cause analysis
    Pipeline->>Pipeline: persisting → save to DB
    Pipeline-->>Gateway: ✅ done — IncidentReport

    Gateway-->>Slack: 🚨 Root cause: OOMKilled<br/>Memory limit 128Mi too low<br/>Fix: kubectl set resources --limits=256Mi
    Slack-->>SRE: Reads diagnosis

    SRE->>SRE: Copies kubectl command
    SRE->>SRE: Applies fix — pod recovers
    Note over SRE: Time from alert to fix: < 2 min
```

### Workflow B: Proactive Scanning

```mermaid
graph LR
    cron["⏰ CronJob<br/>every 15 min"] --> scan["Scan for broken pods<br/>CrashLoopBackOff · OOMKilled · ImagePull"]
    scan --> filter{"Already analysed<br/>in last 1 hour?"}
    filter -->|"no"| submit["POST /api/jobs<br/>for each broken pod"]
    filter -->|"yes"| skip["Skip"]
    submit --> dashboard["Dashboard shows count<br/>of auto-detected failures"]
    dashboard --> alert{"More than 3 failures<br/>in 1 hour?"}
    alert -->|"yes"| oncall["🚨 Alert on-call"]
```

### Workflow C: Chaos Engineering / Fault Injection

```mermaid
sequenceDiagram
    participant SRE as 👨‍💻 Platform Team
    participant Scenario as Scenario Service
    participant K8s as ☸️ K8s API
    participant Pod as demo-app pod
    participant Analyser as Analyser Pipeline
    participant Eval as 📊 Evaluation

    SRE->>Scenario: POST /api/scenarios/05-oom/apply
    Scenario->>K8s: kubectl patch deployment<br/>mem limit → 32Mi
    K8s->>Pod: Pod restarts — OOMKilled
    Note over Pod: Exit Code 137<br/>Exactly like real production OOM

    SRE->>Analyser: POST /api/jobs {demo, demo-app}
    Analyser->>K8s: kubectl logs, describe, events
    Analyser->>Analyser: LLM diagnoses
    Analyser-->>SRE: Report: "OOMKilled · resource · memory limit 32Mi"

    SRE->>Eval: Verify: did LLM correctly identify OOM?
    Eval-->>SRE: ✓ Root cause match · Category match

    SRE->>Scenario: POST /api/scenarios/reset
    Scenario->>K8s: Restore healthy baseline
    Note over SRE: Ready for next scenario<br/>Track score as team health metric
```

---

## 8. Quick-Start Deployment by Platform

### Common First Step (all platforms)

```bash
git clone https://github.com/1hirak/k8s-llm-incident-analyser.git
cd k8s-llm-incident-analyser
cp .env.example .env
# Edit .env: set LLM_PROVIDER=openai (or mock for testing), add API key

# Test locally with Docker Compose first
docker compose up -d
curl http://localhost:8000/health
open http://localhost:3000
```

### AWS EKS

```bash
eksctl create cluster -f cluster.yaml
kubectl create namespace analyser
kubectl apply -k k8s/overlays/production-aws/
# Access via ALB address (kubectl -n analyser get ingress)
```

### Azure AKS

```bash
az aks create -g analyser-prod -n analyser --node-count 3
az aks get-credentials -g analyser-prod -n analyser
kubectl create namespace analyser
kubectl apply -k k8s/overlays/production-azure/
# Access via App Gateway public IP
```

### Custom K8s

```bash
# Prerequisites on any K8s cluster
helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace --set installCRDs=true

# Deploy analyser
kubectl create namespace analyser
kubectl apply -k k8s/overlays/production/
# Point Cloudflare DNS to your load balancer IP
# cert-manager will auto-provision Let's Encrypt TLS
```

---

## 9. Production Readiness Requirements

### Must-have before production use

```mermaid
graph TB
    subgraph PROD["Production Readiness"]
        subgraph INFRA["🏗️ Infrastructure"]
            i1["Multi-node cluster with autoscaling"]
            i2["PostgreSQL with automated backups + PITR"]
            i3["Redis with AOF persistence (or managed)"]
            i4["Ingress + TLS termination"]
            i5["HPA on processor (CPU-based)"]
            i6["PodDisruptionBudget on orchestrator + reports"]
        end

        subgraph SEC["🔒 Security"]
            s1["OIDC/OAuth2 on dashboard login"]
            s2["API key auth on gateway endpoints"]
            s3["Secrets in Vault / Secrets Mgr (never in env)"]
            s4["NetworkPolicies: deny-all + explicit allow"]
            s5["Non-root, read-only root FS, drop capabilities"]
            s6["PodSecurityStandards: restricted"]
            s7["Image vulnerability scanning (Trivy/Snyk)"]
            s8["RBAC: collector read-only, scenario demo-only"]
        end

        subgraph OBS["📊 Observability"]
            o1["Prometheus /metrics on all services"]
            o2["Grafana: pipeline, LLM latency, errors"]
            o3["Structured JSON logs → Loki/CW/LA"]
            o4["Distributed tracing: OTel → Tempo/X-Ray"]
            o5["Alerts: 5xx, queue depth, LLM errors"]
        end

        subgraph CICD["🚀 CI/CD"]
            c1["GitOps pipeline (ArgoCD or Flux)"]
            c2["Environment promotion: staging → prod"]
            c3["Canary or blue-green rollouts"]
        end
    end
```

---

## 10. Estimated Monthly Cost Comparison

| Component | AWS EKS | Azure AKS | Custom (Hetzner) |
|---|---|---|---|
| K8s cluster management | $73 | $0 | $0 |
| Compute (4 worker nodes) | ~$370 | ~$720 | ~€55 |
| PostgreSQL | ~$80 | ~$145 | $0 (in K8s) |
| Redis | ~$17 | ~$190 | $0 (in K8s) |
| LB + TLS + WAF | ~$28 | ~$145 | $0 (CF free) |
| Container registry | ~$5 | ~$20 | $0 (GHCR) |
| Observability | ~$8 | ~$35 | $0 (OSS) |
| Secrets management | ~$3 | ~$1 | $0 (Vault) |
| **Platform subtotal** | **~$580** | **~$1,255** | **~€55** |
| LLM API usage (variable) | per job | per job | per job |

LLM cost: gpt-4o-mini averages ~$0.15 per analysis.
100 analyses/day ≈ $450/month in LLM costs (same across all platforms).

### Cost Breakdown (EKS example)

```mermaid
pie title Monthly EKS Platform Cost (~$580)
    "Compute (4 nodes)" : 370
    "PostgreSQL (RDS)" : 80
    "K8s management" : 73
    "Load Balancer + WAF" : 28
    "Redis (ElastiCache)" : 17
    "Observability" : 8
    "Registry + Secrets" : 8
```

---

## 11. FAQ

**Does this replace Prometheus/Datadog?**
No. Monitoring detects problems. This tool diagnoses root causes.

**Does the LLM see my secrets?**
No. The processor service redacts API keys, passwords, tokens, and connection strings before sending evidence to the LLM provider.

**Can it modify my production workloads?**
No. The collector is read-only. The scenario service only patches a designated test namespace (default: `demo`).

**What if my cluster has no outbound internet?**
Only the LLM service calls external APIs. For air-gapped clusters, run a local LLM (Ollama/vLLM) instead.

**Can I add custom failure categories?**
Yes. Extend the `FailureCategory` enum in the shared contract models.

**Which LLM provider should I use?**
gpt-4o-mini (OpenAI) offers the best cost-quality ratio for incident analysis. Anthropic Claude and DeepSeek are also supported.
