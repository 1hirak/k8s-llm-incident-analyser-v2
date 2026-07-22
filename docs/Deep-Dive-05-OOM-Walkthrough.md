# Deep-Dive: Tracing Scenario 05-oom End-to-End

**Author:** Hirak Das
**Date:** 21 July 2026
**Companion to:** [`Technical-Documentation.md`](./Technical-Documentation.md) — this document is a focused, single-instance walkthrough that complements the broad technical reference.

---

## Table of Contents

1. [Why This Walkthrough](#1-why-this-walkthrough)
2. [The Chosen Instance](#2-the-chosen-instance)
3. [Stage 0 — Fault Injection](#stage-0--fault-injection)
4. [Stage 1 — Collector](#stage-1--collector)
5. [Stage 2 — Preprocessor](#stage-2--preprocessor)
6. [Stage 3 — Redactor](#stage-3--redactor)
7. [Stage 4 — Prompt Builder](#stage-4--prompt-builder)
8. [Stage 5 — LLM Provider](#stage-5--llm-provider)
9. [Stage 6 — Validator + Persistence](#stage-6--validator--persistence)
10. [The IncidentReport](#the-incidentreport)
11. [Evaluation Against Ground Truth](#evaluation-against-ground-truth)
12. [End-to-End Latency Budget](#end-to-end-latency-budget)
13. [Guides](#guides)
14. [Key Observations](#key-observations)

---

## 1. Why This Walkthrough

The [`Technical-Documentation.md`](./Technical-Documentation.md) describes every component of the K8s LLM Incident Analyser in survey form. This document instead takes **a single concrete instance** — scenario `05-oom` — and follows it through every stage of the pipeline, showing the actual data shape at each transformation, with diagrams, tables, and step-by-step guides.

By the end you should be able to:

- Read any `kubectl` output and predict what the analyser will infer.
- Explain why the preprocessor keeps certain lines and drops others.
- Compare what the LLM sees vs. what the baselines see.
- Reproduce the trace on your own cluster.
- Add a new fault scenario using `05-oom` as a template.

---

## 2. The Chosen Instance

We pick **scenario `05-oom`** for three reasons:

| Property | Value | Why it matters for the walkthrough |
|----------|-------|------------------------------------|
| Failure category | `resource` | Distinct from the more common `config`/`crash` scenarios — exercises a different signal path |
| Signal location | `pod_status` + `k8s_events` (not in app logs) | Exposes a non-obvious preprocessor behaviour: log-only filtering |
| Severity | `high` | Forces the LLM to reason about kill behaviour, not just a missing var |
| Detectable by baselines | Yes (both keyword and rule-based) | Lets us compare 3 classifiers on the same evidence |
| Reproducible | One-line `kubectl patch` | Easy to follow along on minikube/k3s |

**The story in one sentence:** the demo app's Deployment is patched so its memory limit drops from `128Mi` to `32Mi`; when someone hits the `/fault/oom` endpoint, the app tries to allocate 600 MB and the kernel OOM-kills the container; the analyser is then invoked to diagnose the resulting restart loop.

---

## Stage 0 — Fault Injection

### Cluster state: before vs. after

```mermaid
flowchart LR
    subgraph Before["Before patch (healthy)"]
        B_Pod["demo-app pod\nMemory limit: 128Mi\nState: Running\nReady: True\nRestarts: 0"]
    end
    subgraph After["After kubectl patch + /fault/oom hit"]
        A_Pod["demo-app pod\nMemory limit: 32Mi\nState: Running (after restart)\nReady: True\nRestarts: 3\nLast State: OOMKilled\nExit Code: 137"]
    end
    Before -->|"kubectl patch + curl /fault/om"| After
```

### The strategic merge patch

`k8s/scenarios/05-oom/fault.yaml` — the entire fault is 17 lines:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-app
  namespace: demo
spec:
  template:
    spec:
      containers:
      - name: demo-app
        resources:
          limits:
            memory: "32Mi"      # was 128Mi in k8s/base/deployment.yaml:35
            cpu: "200m"
          requests:
            memory: "32Mi"
            cpu: "100m"
```

### Why this triggers OOMKilled

The demo app's `/fault/oom` endpoint (`demo-app/app/main.py:51`) does:

```python
@app.get("/fault/oom")
def fault_oom():
    logger.warning("Memory allocation stress test starting...")
    data = [bytearray(1024 * 1024) for _ in range(600)]  # 600 MB
    return {"allocated": len(data)}
```

| Memory budget | Available | Requested | Outcome |
|---------------|-----------|-----------|---------|
| Container limit (post-patch) | 32 MiB | 600 MiB | Kernel OOM-killer terminates the process with signal 9 |
| Container limit (pre-patch) | 128 MiB | 600 MiB | Same outcome — the patch just makes it fail on the first request, every time |

The kubelet restarts the container; `restartCount` climbs; the pod's `containerStatuses[0].lastState.reason` becomes `OOMKilled` with `exitCode: 137`.

### Guide: Reproduce the fault

```bash
# 1. Start a cluster and load images
minikube start
eval $(minikube docker-env)
docker build -t demo-app:latest ./demo-app
docker build -t analyser:latest .

# 2. Apply the healthy baseline + analyser
kubectl apply -f k8s/base/
kubectl apply -f k8s/analyser/
kubectl rollout status deployment/demo-app -n demo

# 3. Inject the OOM fault
./scripts/run_scenario.sh 05-oom

# 4. Wait ~30s, then trigger the OOM by hitting the endpoint via port-forward
kubectl port-forward -n demo svc/demo-app-svc 8001:80 &
curl http://localhost:8001/fault/oom    # pod will be killed within seconds

# 5. Watch the restart count climb
kubectl get pods -n demo -w

# 6. Reset to healthy when done
./scripts/run_scenario.sh reset
```

---

## Stage 1 — Collector

### Trigger

The on-call engineer invokes the analyser:

```bash
curl -X POST http://localhost:8000/analyse/pod/demo/demo-app
```

Note `demo-app` is the **Deployment** name, not a pod name. The collector handles this transparently.

### kubectl call sequence

`app/core/collector.py:112` (`KubernetesCollector.collect`) issues up to 8 subprocess calls. For our instance, the exact sequence is:

```mermaid
sequenceDiagram
    autonumber
    participant API as /analyse endpoint
    participant C as KubernetesCollector
    participant K as kubectl
    participant K8s as kube-apiserver

    API->>C: collect("demo", "demo-app")
    C->>K: get pod demo-app -n demo -o jsonpath={.metadata.name} --ignore-not-found
    K->>K8s: GET /api/v1/namespaces/demo/pods/demo-app
    K8s-->>K: (empty — no pod named "demo-app" exists)
    K-->>C: "" (empty)
    Note over C: _pod_exists returns False\n→ fall back to label selector
    C->>K: get pods -n demo -l app=demo-app -o jsonpath={.items[0].metadata.name}
    K->>K8s: GET /api/v1/namespaces/demo/pods?labelSelector=app=demo-app
    K8s-->>K: "demo-app-abc123"
    K-->>C: "demo-app-abc123"
    Note over C: actual_pod = "demo-app-abc123"
    C->>K: logs demo-app-abc123 -n demo --tail=500 --timestamps=true
    K-->>C: "" (container killed before flushing stdout)
    C->>K: logs demo-app-abc123 -n demo --tail=500 --timestamps=true --previous
    K-->>C: "Memory allocation stress test starting..." (×3)
    C->>K: describe pod demo-app-abc123 -n demo
    K-->>C: full describe output (Last State: OOMKilled)
    C->>K: get events -n demo --sort-by=.metadata.creationTimestamp
    K-->>C: Killing + BackOff + Normal events
    C->>K: get pod ... -o jsonpath={.status.containerStatuses[0].restartCount}
    K-->>C: "3"
    C->>K: get pod ... -o jsonpath={.status.containerStatuses}
    K-->>C: '[{"name":"demo-app",...,"lastState":{"reason":"OOMKilled",...}}]'
    C-->>API: RawEvidence(...)
```

### kubectl command reference (for this instance)

| # | Command | Purpose | Sample output (truncated) |
|---|---------|---------|---------------------------|
| 1 | `kubectl get pod demo-app -n demo -o jsonpath={.metadata.name} --ignore-not-found` | Existence check | `""` (no pod with that exact name) |
| 2 | `kubectl get pods -n demo -l app=demo-app -o jsonpath={.items[0].metadata.name}` | Label fallback | `"demo-app-abc123"` |
| 3 | `kubectl logs demo-app-abc123 -n demo --tail=500 --timestamps=true` | Current container logs | `""` (killed before flush) |
| 4 | `kubectl logs demo-app-abc123 -n demo --tail=500 --timestamps=true --previous` | Previous container logs | `"2026-... WARNING Memory allocation stress test starting..."` × 3 |
| 5 | `kubectl describe pod demo-app-abc123 -n demo` | Pod status with Last State | `Containers:\n  demo-app:\n    State: Running\n    Last State: Terminated\n      Reason: OOMKilled\n      Exit Code: 137\n    Restart Count: 3\nEvents:\n  Warning Killing ...` |
| 6 | `kubectl get events -n demo --sort-by=.metadata.creationTimestamp` | Namespace events | `Warning Killing ... OOMKilled\nWarning BackOff ... restarting\nNormal Pulled ...\nNormal Created ...\nNormal Started ...` |
| 7 | `kubectl get pod ... -o jsonpath={.status.containerStatuses[0].restartCount}` | Restart count | `"3"` |
| 8 | `kubectl get pod ... -o jsonpath={.status.containerStatuses}` | Container state JSON | `[{...,"lastState":{"reason":"OOMKilled","exitCode":137},...}]` |

### The resulting `RawEvidence` dataclass

`app/core/collector.py:9` defines the dataclass. For our instance, after `collect()` returns:

```python
RawEvidence(
    namespace="demo",
    pod_name="demo-app-abc123",                # resolved via label fallback
    current_logs="",                            # killed container wrote nothing
    previous_logs=(
        "2026-07-21T10:01:00Z WARNING Memory allocation stress test starting...\n"
        "2026-07-21T10:01:01Z WARNING Memory allocation stress test starting...\n"
        "2026-07-21T10:01:02Z WARNING Memory allocation stress test starting...\n"
        # then SIGKILL — no further output
    ),
    pod_status=(
        "Name:         demo-app-abc123\n"
        "Namespace:    demo\n"
        "...\n"
        "Containers:\n"
        "  demo-app:\n"
        "    State:          Running\n"
        "    Last State:      Terminated\n"
        "      Reason:       OOMKilled\n"
        "      Exit Code:    137\n"
        "    Ready:          True\n"
        "    Restart Count:  3\n"
        "Events:\n"
        "  Warning  Killing  2m  Container demo-app was killed due to OOMKilled\n"
        "  Warning  BackOff  1m  Back-off restarting failed container"
    ),
    k8s_events=(
        "LAST SEEN  TYPE     REASON    OBJECT           MESSAGE\n"
        "2m         Warning  Killing   pod/demo-app     Container demo-app was killed due to OOMKilled\n"
        "1m         Warning  BackOff   pod/demo-app     Back-off restarting failed container\n"
        "5m         Normal   Pulled    pod/demo-app     Successfully pulled image demo-app:latest\n"
        "5m         Normal   Created   pod/demo-app     Created container demo-app\n"
        "5m         Normal   Started   pod/demo-app     Started container demo-app"
    ),
    restart_count=3,
    container_states=[
        {
            "name": "demo-app",
            "restartCount": 3,
            "lastState": {"reason": "OOMKilled", "exitCode": 137},
            "ready": True,
            "state": {"running": {"startedAt": "2026-07-21T10:01:05Z"}}
        }
    ],
)
```

### Key design choices that matter here

| Choice | Code reference | Effect on 05-oom |
|--------|----------------|------------------|
| Label-based pod resolution | `collector.py:115-119` | Engineer can `POST /analyse/pod/demo/demo-app` instead of looking up the random pod name first |
| `--previous` logs | `collector.py:50-52` | Captures the killed container's last output (only signal we have from the application) |
| JSONPath for restart count | `collector.py:67-75` | Avoids regex on `kubectl describe`; returns `0` on parse failure (safe default) |
| 30-second timeout per call | `collector.py:22` | A hung kubectl can't block the API indefinitely |

---

## Stage 2 — Preprocessor

### What it does — in one diagram

```mermaid
flowchart LR
    subgraph In["RawEvidence (Stage 1 output)"]
        In1["current_logs\n(previous container killed)"]
        In2["previous_logs\n(WARNING lines)"]
        In3["pod_status\n(describe output)"]
        In4["k8s_events\n(Killing + BackOff + Normal)"]
        In5["restart_count = 3"]
    end
    subgraph Filter["LogPreprocessor._filter_with_context"]
        F1["Drop noise lines\n(GET /health, /ready, /metrics, blanks)"]
        F2["Keep signal lines\n(error|exception|oomkilled|crashloopbackoff|...)"]
        F3["Add ±3 line context window"]
        F4["Deduplicate identical lines"]
        F5["Cap at 100 lines"]
    end
    subgraph Out["EvidencePackage (Stage 2 output)"]
        Out1["current_logs (filtered)"]
        Out2["previous_logs (filtered)"]
        Out3["pod_status_summary\n(truncated to 2000 chars)"]
        Out4["k8s_events_filtered\n(Warning or signal lines only)"]
        Out5["restart_count = 3"]
    end
    In1 --> Filter
    In2 --> Filter
    In3 --> Out3
    In4 --> Out4
    In5 --> Out5
    Filter --> Out1
    Filter --> Out2
```

### Field-by-field transformation for 05-oom

| Field | Input (Stage 1) | Filter behaviour | Output (Stage 2) |
|-------|-----------------|------------------|------------------|
| `current_logs` | `""` | No lines to filter | `""` |
| `previous_logs` | 3× `"Memory allocation stress test starting..."` | None of these match `SIGNAL_PATTERNS` (`error`, `exception`, `oomkilled`, `crashloopbackoff`, `missing`, `not found`, etc.) | `""` (everything filtered out) |
| `pod_status` | full describe (~1.5 KB) | Truncated to `[:2000]` chars — no content filtering | full describe (unchanged, well under 2000) |
| `k8s_events` | 5 events (2 Warning + 3 Normal) | `_extract_events` keeps Warning lines OR signal-matching lines | 2 lines: `Killing` + `BackOff` |
| `restart_count` | `3` | Passed through | `3` |

### Critical observation: the signal is in `pod_status`, not in the logs

For 05-oom, the **only** places the word `OOMKilled` appears are `pod_status` (in the Last State section of `kubectl describe`) and `k8s_events` (the `Killing` event). The preprocessor's noise/signal filter only operates on **log text** — it does not scan `pod_status` or `k8s_events` for signal patterns. Those fields pass through largely intact.

This means for this scenario:

- The preprocessor's "noise reduction" value is near zero (the app logs have no noise because the container was killed instantly).
- The LLM gets the full pod describe output in the prompt and identifies `OOMKilled` from there.
- The mock provider (`app/core/llm/mock_provider.py:15-17`) compensates by explicitly checking `package.pod_status_summary.lower()` for `oomkilled` and `memory`.

### The resulting `EvidencePackage`

This is exactly the canonical fixture in `tests/fixtures/scenario_evidence.py:169`:

```python
EvidencePackage(
    namespace="demo",
    pod_name="demo-app-abc123",
    current_logs="",
    previous_logs="",
    pod_status_summary=(
        "Name:         demo-app-abc123\n"
        "Namespace:    demo\n"
        "Containers:\n"
        "  demo-app:\n"
        "    State:          Running\n"
        "    Last State:      Terminated\n"
        "      Reason:       OOMKilled\n"
        "      Exit Code:    137\n"
        "    Ready:          True\n"
        "    Restart Count:  3\n"
        "Events:\n"
        "  Warning  Killing  2m  Container demo-app was killed due to OOMKilled"
    ),
    k8s_events_filtered=(
        "Warning Killing: Container demo-app was killed due to OOMKilled\n"
        "Warning BackOff: Back-off restarting failed container"
    ),
    restart_count=3,
)
```

---

## Stage 3 — Redactor

### What it does

`app/core/redactor.py:19` applies 7 regex patterns to every text field of the `EvidencePackage`. Patterns are applied in list order; each match is replaced with a category tag.

### Pattern order and rationale

```mermaid
flowchart TD
    Start["EvidencePackage text fields"] --> P1
    P1["1. password/ passwd/ pwd=\n→ [PASSWORD=REDACTED]"] --> P2
    P2["2. api_key / token / secret=\n→ [API_KEY=REDACTED]"] --> P3
    P3["3. sk-ant-...\n→ [ANTHROPIC_KEY=REDACTED]"] --> P4
    P4["4. sk-...\n→ [OPENAI_KEY=REDACTED]"] --> P5
    P5["5. (postgres|mysql|mongodb|redis)://...\n→ [DB_URL=REDACTED]"] --> P6
    P6["6. Authorization / Bearer ...\n→ [AUTH_HEADER=REDACTED]"] --> P7
    P7["7. email@domain\n→ [EMAIL=REDACTED]"] --> Out
    Out["Redacted EvidencePackage"]
```

| Pattern # | Why this order |
|-----------|----------------|
| 1 (password) | Run first so the value is masked before any later pattern can leak it |
| 3 (sk-ant-) → 4 (sk-) | Anthropic keys are a strict prefix superset of OpenAI keys; running OpenAI first would leave `ant-api03-xyz...` exposed |
| 5 (DB URL) | Catches full connection strings before bearer/auth patterns can fragment them |

### For our 05-oom instance

| Field | Contains secrets? | Result |
|-------|-------------------|--------|
| `current_logs` (`""`) | No | `""` |
| `previous_logs` (`""`) | No | `""` |
| `pod_status_summary` | No — only pod metadata, no env values are printed by `kubectl describe pod` for this scenario | unchanged |
| `k8s_events_filtered` | No — only Warning events with pod name and reason | unchanged |

**For 05-oom the redactor is a no-op.** This is the expected case for most pod-failure scenarios: redaction fires defensively only when secrets are present in the evidence (e.g. an app that logs its `DATABASE_URL=postgres://user:pass@host` on startup).

### What redaction would look like if secrets were present

If the previous logs had been `"connecting to postgresql://admin:s3cr3t@db:5432/prod"` instead of `"Memory allocation stress test starting..."`, pattern 5 would have fired:

```
Before: "connecting to postgresql://admin:s3cr3t@db:5432/prod"
After:  "connecting to [DB_URL=REDACTED]"
```

This is verified by `tests/integration/test_pipeline.py:160` (`TestRedactionInPipeline.test_api_key_redacted_before_llm`), which plants `api_key=sk-...` and `password=supersecret123` in the logs and asserts the redacted tags appear in the final evidence.

### The privacy guarantee

After Stage 3, the `EvidencePackage` can be sent to any third-party LLM vendor without leaking credentials. This is the **non-negotiable control** that makes the architecture safe for production use.

---

## Stage 4 — Prompt Builder

### Prompt structure

`app/core/prompts.py:49` (`build_prompt`) returns a `(system, user)` tuple. The LLM sees both; the system prompt sets behaviour, the user prompt carries the evidence.

```mermaid
flowchart TB
    subgraph System["System prompt (~150 tokens)"]
        S1["Role: 'You are a Kubernetes incident analyst'"]
        S2["5 rules:
             • only use given evidence
             • do not invent log lines
             • lower confidence if ambiguous
             • no auto-remediation
             • JSON only, matching schema"]
    end
    subgraph User["User prompt (~1.5-3 KB)"]
        U1["Header + namespace + target + timestamp"]
        U2["POD STATUS section\n(kubectl describe output)"]
        U3["CURRENT LOGS section\n(filtered, or '(no current logs)')"]
        U4["PREVIOUS LOGS section\n(filtered, or '(no previous logs)')"]
        U5["KUBERNETES EVENTS section\n(filtered warnings)"]
        U6["RESTART COUNT"]
        U7["REQUIRED OUTPUT SCHEMA\n(full IncidentReport JSON Schema, ~800 tokens)"]
    end
    System --> LLM
    User --> LLM
    LLM["LLM Provider"]
```

### The exact system prompt

```
You are a Kubernetes incident analyst. Your task is to analyse the provided
diagnostic evidence from a Kubernetes environment and produce a structured
incident report.

Rules:
- Only use evidence that is present in the provided data.
- Do not invent log lines or events that were not given.
- Set confidence lower if evidence is ambiguous or incomplete.
- Never recommend automated remediation -- suggest human-verifiable steps only.
- Respond ONLY with a valid JSON object matching the schema below.
```

### The user prompt for 05-oom (with placeholders filled in)

```
=== KUBERNETES DIAGNOSTIC EVIDENCE ===

Namespace: demo
Target: demo-app-abc123
Collection Time: 2026-07-21T10:05:33.482119+00:00

--- POD STATUS ---
Name:         demo-app-abc123
Namespace:    demo
Containers:
  demo-app:
    State:          Running
    Last State:      Terminated
      Reason:       OOMKilled
      Exit Code:    137
    Ready:          True
    Restart Count:  3
Events:
  Warning  Killing  2m  Container demo-app was killed due to OOMKilled

--- APPLICATION LOGS (current) ---
(no current logs)

--- APPLICATION LOGS (previous container, if available) ---
(no previous logs)

--- KUBERNETES EVENTS ---
Warning Killing: Container demo-app was killed due to OOMKilled
Warning BackOff: Back-off restarting failed container

--- RESTART COUNT ---
3

=== REQUIRED OUTPUT SCHEMA ===
{
  "$defs": {
    "EvidenceItem": {
      "properties": {
        "source": {"enum": ["pod_log", "previous_pod_log", "kubernetes_event", "pod_status"], ...},
        "pod": {"type": "string"},
        "timestamp": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null},
        "evidence": {"type": "string"}
      },
      "required": ["source", "pod", "evidence"],
      "title": "EvidenceItem",
      "type": "object"
    }
  },
  "properties": {
    "incident_summary": {"minLength": 10, "type": "string"},
    "likely_root_cause": {"minLength": 10, "type": "string"},
    "affected_component": {"type": "string"},
    "failure_category": {"enum": ["crash","config","dependency","network","image","resource","probe","unknown"]},
    "severity": {"enum": ["low","medium","high","critical"]},
    "confidence": {"maximum": 1.0, "minimum": 0.0, "type": "number"},
    "supporting_evidence": {"items": {"$ref": "#/$defs/EvidenceItem"}, "minItems": 1, "type": "array"},
    "suggested_fix": {"type": "string"},
    "recommended_commands": {"items": {"type": "string"}, "type": "array"},
    "human_verification_steps": {"items": {"type": "string"}, "type": "array"}
  },
  "required": ["incident_summary", "likely_root_cause", "affected_component",
               "failure_category", "severity", "confidence", "supporting_evidence",
               "suggested_fix", "recommended_commands", "human_verification_steps"],
  "title": "IncidentReport",
  "type": "object"
}

Analyse the evidence above and return a JSON object matching the schema.
```

### Token budget breakdown (approximate)

| Section | Tokens | Notes |
|---------|--------|-------|
| System prompt | ~150 | Static across all calls |
| User header + section labels | ~50 | Static template |
| `pod_status_summary` | ~250 | Dominates user-prompt variability for 05-oom |
| `current_logs` | ~5 | `(no current logs)` |
| `previous_logs` | ~5 | `(no previous logs)` |
| `k8s_events_filtered` | ~40 | Two warning lines |
| `restart_count` | ~3 | Just the number |
| JSON schema | ~800 | Static across all calls |
| **Total input** | **~1300** | Well under typical 8K-128K context windows |
| **Output budget** | 2000 | `LLM_MAX_TOKENS` env var, default `2000` |

For a noisier scenario (e.g. 01-missing-env where the previous logs contain a Traceback), `current_logs` + `previous_logs` can add 300-800 tokens, but the preprocessor's 100-line cap keeps it bounded.

---

## Stage 5 — LLM Provider

### Factory + provider selection

`app/core/llm/__init__.py:9` (`get_provider`) reads `LLM_PROVIDER` env var:

```mermaid
flowchart TD
    Env["LLM_PROVIDER env var"] --> Check
    Check{"Value?"}
    Check -->|mock| Mock["MockProvider\nno API call"]
    Check -->|openai| OA["OpenAIProvider\nchat.completions.parse()"]
    Check -->|anthropic| AN["AnthropicProvider\nmessages.parse()"]
    Check -->|deepseek| DS["DeepSeekProvider\nhttpx + json_object"]
    Check -->|unknown| Fallback["MockProvider\n+ log warning"]
```

### Same `EvidencePackage`, four different code paths

| Provider | SDK call | Schema enforcement | Output path |
|----------|----------|---------------------|-------------|
| **mock** | None — pure Python heuristic | None — `IncidentReport` constructed directly | `mock_provider.py:23` returns hardcoded `IncidentReport` |
| **openai** | `client.chat.completions.parse(response_format=IncidentReport)` | Native (Structured Outputs GA) — SDK returns `message.parsed` as a validated `IncidentReport` | `openai_provider.py:28-46` |
| **anthropic** | `client.messages.parse(output_format=IncidentReport)` | Native — SDK returns `response.content[0].parsed_output` | `anthropic_provider.py:25-36` |
| **deepseek** | `httpx.AsyncClient().post(..., response_format={type: json_object})` | Prompt-injected — schema appended to system prompt via `_JSON_INSTRUCTION_TEMPLATE`; response is `json.loads` + `IncidentReport.model_validate` | `deepseek_provider.py:32-70` |

### Mock provider — exact output for 05-oom

`app/core/llm/mock_provider.py:8` runs this heuristic:

```python
logs = (package.current_logs + package.previous_logs).lower()       # "" for 05-oom

if "oomkilled" in logs or "memory" in logs or \
        "memory" in package.pod_status_summary.lower():
    category, cause = "resource", "Container exceeded memory limit (OOMKilled)"
```

The `logs` variable is empty, but `package.pod_status_summary.lower()` contains both `"oomkilled"` (from the Events section) and `"memory"` (nowhere actually — only `OOMKilled` and `Killing`). The `"oomkilled" in ...pod_status_summary.lower()` check fires → `category = "resource"`.

**Mock provider output for 05-oom:**

```python
IncidentReport(
    incident_id="inc-a1b2c3d4e5f6",                     # uuid4 hex[:12]
    incident_summary="[MOCK] Failure detected in demo-app-abc123",
    likely_root_cause="Container exceeded memory limit (OOMKilled)",
    affected_component="demo-app-abc123",
    failure_category="resource",                         # ✓ correct
    severity="medium",                                   # mock is always medium
    confidence=0.5,                                      # mock is always 0.5
    supporting_evidence=[
        EvidenceItem(
            source="pod_log",                            # mock always cites pod_log
            pod="demo-app-abc123",
            timestamp=None,
            evidence="(no logs)",                        # current_logs[:200] = ""
        )
    ],
    suggested_fix="[MOCK] Investigate the reported root cause.",
    recommended_commands=["kubectl describe pod -n demo demo-app-abc123"],
    human_verification_steps=["Check the logs manually", "Verify environment variables"],
)
```

### Real LLM — expected output for 05-oom (synthesised from eval runs)

A real LLM (e.g. `deepseek-chat`) typically returns something like:

```python
IncidentReport(
    incident_id="inc-9f2a1b7c3e04",
    incident_summary="The demo-app container is being repeatedly killed by the Kubernetes OOM-killer after exceeding its 32Mi memory limit, causing restart cycles.",
    likely_root_cause="The container's memory limit (32Mi) is far below the application's runtime requirement. The /fault/oom endpoint triggers a 600MB allocation that immediately exceeds the cgroup memory limit, invoking the kernel OOM-killer which terminates the process with SIGKILL (exit code 137).",
    affected_component="demo-app container / deployment resources",
    failure_category="resource",                         # ✓ correct
    severity="high",                                     # ✓ matches ground truth
    confidence=0.85,
    supporting_evidence=[
        EvidenceItem(
            source="pod_status",
            pod="demo-app-abc123",
            timestamp=None,
            evidence="Last State: Terminated, Reason: OOMKilled, Exit Code: 137",
        ),
        EvidenceItem(
            source="kubernetes_event",
            pod="demo-app-abc123",
            timestamp=None,
            evidence="Warning Killing: Container demo-app was killed due to OOMKilled",
        ),
    ],
    suggested_fix="Increase the container memory limit in the deployment spec. The current 32Mi limit is insufficient for the application's working set. Consider 256Mi or higher based on observed usage.",
    recommended_commands=[
        "kubectl patch deployment demo-app -n demo --type strategic -p "
        "'{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"demo-app\","
        "\"resources\":{\"limits\":{\"memory\":\"256Mi\"}}}]}}}}}'",
        "kubectl rollout status deployment/demo-app -n demo",
    ],
    human_verification_steps=[
        "Confirm the pod reaches Running state with no further OOMKilled events",
        "Monitor memory usage with kubectl top pod -n demo",
        "Re-test the /fault/oom endpoint to verify the new limit is sufficient",
    ],
)
```

### Side-by-side: mock vs. real LLM on the same evidence

| Field | Mock | Real LLM | Ground truth |
|-------|------|----------|--------------|
| `failure_category` | `resource` ✓ | `resource` ✓ | `resource` |
| `severity` | `medium` ✗ | `high` ✓ | `high` |
| `confidence` | `0.5` | `0.85` | (n/a) |
| `likely_root_cause` | "Container exceeded memory limit (OOMKilled)" | Detailed explanation citing the 32Mi limit, /fault/oom, SIGKILL, exit code 137 | "Container exceeded memory limit and was terminated by OOMKiller" |
| `supporting_evidence` | 1 item, wrong source (`pod_log` with `(no logs)`) | 2 items, correct sources (`pod_status` + `kubernetes_event`) | (n/a) |
| `suggested_fix` | "[MOCK] Investigate..." | Specific patch command with 256Mi suggestion | (n/a) |
| `recommended_commands` | 1 generic `kubectl describe` | 2 actionable commands (patch + rollout status) | (n/a) |
| `remediation_keywords_hit` | 0 / 5 | 4 / 5 (`memory`, `limit`, `resources`, `deployment`) | 5 keywords in ground truth |

The mock gets the category right by heuristic luck but fails every qualitative metric. This gap is exactly what the evaluation harness is designed to surface.

---

## Stage 6 — Validator + Persistence

### Validation

For providers using structured outputs (OpenAI, Anthropic), validation is implicit — the SDK returns a parsed Pydantic object. For DeepSeek, `IncidentReport.model_validate(raw_json)` (`deepseek_provider.py:70`) is the safety net. For the mock, validation is trivially true since the report is constructed directly.

`ReportValidator` (`app/core/validator.py:8`) is invoked explicitly only by the evaluation harness to compute the `schema_valid` metric:

```python
validator = ReportValidator()
schema_valid = validator.is_valid(report.model_dump())   # True for 05-oom
```

### Persistence flow

Back in `app/api/analyse.py:32-35`:

```python
try:
    save_report(report)
except Exception as persist_err:
    log.warning("report_persist_failed", id=request_id, error=str(persist_err))
```

`save_report` (`persistence.py:24`) writes one JSON file per report.

```mermaid
flowchart LR
    Report["IncidentReport object"] --> Dump["report.model_dump_json(indent=2)"]
    Dump --> File["reports/{unix_ts}_{incident_id}.json"]
    File --> Disk[("disk")]
```

### File written for our 05-oom instance

**Path:** `reports/1721577933_inc-a1b2c3d4e5f6.json`

**Contents (mock provider, ~1.2 KB):**

```json
{
  "incident_id": "inc-a1b2c3d4e5f6",
  "incident_summary": "[MOCK] Failure detected in demo-app-abc123",
  "likely_root_cause": "Container exceeded memory limit (OOMKilled)",
  "affected_component": "demo-app-abc123",
  "failure_category": "resource",
  "severity": "medium",
  "confidence": 0.5,
  "supporting_evidence": [
    {
      "source": "pod_log",
      "pod": "demo-app-abc123",
      "timestamp": null,
      "evidence": "(no logs)"
    }
  ],
  "suggested_fix": "[MOCK] Investigate the reported root cause.",
  "recommended_commands": [
    "kubectl describe pod -n demo demo-app-abc123"
  ],
  "human_verification_steps": [
    "Check the logs manually",
    "Verify environment variables"
  ]
}
```

### Why persistence failures are non-fatal

The report is already in the API response body before `save_report` is called. If the disk fills up or permissions break, the engineer still gets the diagnosis — only the listing/retrieval endpoints degrade. This is a deliberate resilience choice.

### Listing/retrieval endpoints after this write

```bash
$ curl http://localhost:8000/reports
{
  "reports": [
    {
      "incident_id": "inc-a1b2c3d4e5f6",
      "incident_summary": "[MOCK] Failure detected in demo-app-abc123",
      "failure_category": "resource",
      "severity": "medium",
      "confidence": 0.5,
      "file": "1721577933_inc-a1b2c3d4e5f6.json"
    }
  ],
  "count": 1
}

$ curl http://localhost:8000/reports/inc-a1b2c3d4e5f6
{ ...full IncidentReport JSON... }
```

---

## The IncidentReport

### The contract — annotated

`app/models/incident.py:14` defines the Pydantic model. Here's the mock's output for 05-oom with each field annotated:

```mermaid
classDiagram
    class IncidentReport {
        +incident_id: str          # auto-generated inc-{uuid4[:12]}
        +incident_summary: str     # min_length=10
        +likely_root_cause: str    # min_length=10
        +affected_component: str
        +failure_category: enum8
        +severity: enum4
        +confidence: float         # 0.0 ≤ x ≤ 1.0
        +supporting_evidence: list~EvidenceItem~  # min_length=1
        +suggested_fix: str
        +recommended_commands: list~str~
        +human_verification_steps: list~str~
    }
    class EvidenceItem {
        +source: enum4   # pod_log | previous_pod_log | kubernetes_event | pod_status
        +pod: str
        +timestamp: str?
        +evidence: str
    }
    IncidentReport "1" --> "*" EvidenceItem
```

### Schema validation rules (enforced by Pydantic)

| Rule | Where enforced | Effect on LLM output |
|------|----------------|----------------------|
| `failure_category` must be one of 8 enum values | `incident.py:8-10` | LLM cannot invent a 9th category |
| `severity` must be one of 4 enum values | `incident.py:11` | LLM cannot return `"severe"` or `"moderate"` |
| `confidence` must be a float in `[0.0, 1.0]` | `incident.py:21` | LLM cannot return `"high"` as confidence |
| `supporting_evidence` must have `min_length=1` | `incident.py:22` | LLM cannot return an empty evidence list |
| `incident_summary` must have `min_length=10` | `incident.py:16` | LLM cannot return `"bad"` |
| `model_config = {"extra": "ignore"}` | `incident.py:26` | Extra LLM fields (`priority`, `next_steps`, ...) silently dropped, not rejected |

The `"extra": "ignore"` choice is deliberate: LLMs occasionally add fields that aren't in the schema. Rejecting the whole report would be brittle; silently dropping is graceful.

---

## Evaluation Against Ground Truth

### The scoring flow

When the eval harness runs scenario 05-oom, it executes the same pipeline and then scores the resulting `IncidentReport` against the ground truth file:

```mermaid
sequenceDiagram
    autonumber
    participant H as EvaluationHarness
    participant C as Collector
    participant P as Preprocessor
    participant R as Redactor
    participant Cl as Classifier (mock/llm/keyword/rulebased)
    participant M as metrics.evaluate
    participant GT as ground_truth/05-oom.json

    H->>C: collect("demo", "demo-app")
    C-->>H: RawEvidence
    H->>P: process(raw)
    P-->>H: EvidencePackage
    H->>R: redact(package)
    R-->>H: EvidencePackage (redacted)
    H->>Cl: classify(safe)
    Cl-->>H: IncidentReport
    H->>M: evaluate(report, gt_path, latency)
    M->>GT: read 05-oom.json
    GT-->>M: true_root_cause, true_failure_category, correct_remediation_keywords
    M->>M: compare report vs ground truth
    M-->>H: EvaluationResult
```

### Ground truth for 05-oom

`evaluation/ground_truth/05-oom.json`:

```json
{
  "scenario_id": "05-oom",
  "description": "Container memory limit reduced to 32Mi causing OOMKilled when app allocates memory",
  "true_root_cause": "Container exceeded memory limit and was terminated by OOMKiller",
  "true_affected_component": "demo-app",
  "true_failure_category": "resource",
  "true_severity": "high",
  "expected_log_patterns": ["OOMKilled", "memory", "out of memory", "memory allocation"],
  "expected_event_reasons": ["Killing", "BackOff"],
  "correct_remediation_keywords": ["memory", "limit", "resources", "container", "deployment"],
  "notes": "Pod status will show Reason: OOMKilled. Requires /fault/oom endpoint to be hit."
}
```

### Per-metric scoring for 05-oom

`evaluation/metrics.py:41` (`evaluate`) computes 7 metrics. Here's how they score for our instance across all 3 classifiers:

| Metric | How computed | Mock | Keyword | Rule-based | Real LLM (DeepSeek) |
|--------|--------------|------|---------|-----------|---------------------|
| `scenario_id` | from ground truth | `05-oom` | `05-oom` | `05-oom` | `05-oom` |
| `category_correct` | `report.failure_category == "resource"` | ✓ | ✓ | ✓ | ✓ |
| `root_cause_correct` | word overlap (len>4) between `report.likely_root_cause` and `"Container exceeded memory limit and was terminated by OOMKiller"` | ✓ (matches on `container`, `exceeded`, `memory`, `limit`, `oomkilled`) | ✓ (baseline text includes `"Container exceeded memory or CPU limit and was killed by the kernel."` → matches `container`, `exceeded`, `memory`, `killed`) | ✓ (same as keyword) | ✓ (matches `container`, `exceeded`, `memory`, `limit`, `terminated`, `oomkiller`) |
| `schema_valid` | `ReportValidator.is_valid(report.model_dump())` | ✓ | ✓ (constructed via `_make_report_from_dict`) | ✓ | ✓ |
| `latency_s` | monotonic delta around `collect → classify` | ~0.05s | <0.001s | <0.001s | ~6.7s |
| `confidence` | `report.confidence` | 0.5 | 0.6 | 0.6 | 0.85 |
| `evidence_count` | `len(supporting_evidence)` | 1 | 1 | 1 | 2 |
| `remediation_keywords_hit` | count of `["memory","limit","resources","container","deployment"]` found in `suggested_fix + recommended_commands + human_verification_steps` (lowercased) | 0 / 5 | 4 / 5 (baseline fix: "Increase memory/CPU limits in the deployment resource spec." → hits `memory`, `limit`, `resources`, `deployment`) | 4 / 5 (same) | 4 / 5 (LLM fix mentions `memory`, `limit`, `resources`, `deployment`) |

### Why the keyword/rule-based baselines do so well on 05-oom

Both baselines have a `resource` rule that fires on `OOMKilled` in the pod status text:

- **Keyword** (`evaluation/baselines/keyword.py:84`): `"oomkilled": 3` (Tier 1, definitive) → score 3 → wins.
- **Rule-based** (`evaluation/baselines/rulebased.py:91-104`): `_resource_rule` checks `_extract_reasons(pod_status)` for `oomkilled` → first match in priority order → returns `resource`.

For 05-oom the signal is unambiguous, so all three classifiers get the category right. The differentiation shows up in the qualitative metrics (`remediation_keywords_hit`, `confidence`, `evidence_count`) — and that's the research finding: **when the signal is clear, baselines match the LLM on category; when the signal is subtle, the LLM pulls ahead on remediation specificity.**

---

## End-to-End Latency Budget

Where the wall time goes for a single 05-oom analysis (real LLM, EC2 t3.small):

```mermaid
gantt
    title 05-oom analysis wall time (~6.8s)
    dateFormat ss
    axisFormat %S
    section kubectl
    Existence + label resolve   :0, 1
    Logs + describe + events    :1, 3
    section Preprocess
    Filter + extract            :3, 4
    section Redact
    7 regex patterns            :4, 4
    section LLM
    HTTPS round-trip            :4, 11
    section Persist
    Write JSON to disk          :11, 11
```

| Stage | Wall time | % of total | Notes |
|-------|-----------|------------|-------|
| Stage 1 (Collector) | ~1.0s | ~15% | 8 kubectl subprocess calls; dominated by `describe pod` |
| Stage 2 (Preprocessor) | ~50ms | <1% | Pure Python regex over small text |
| Stage 3 (Redactor) | ~10ms | <1% | 7 regex patterns over 4 text fields |
| Stage 4 (Prompt builder) | ~5ms | <1% | `.format()` + `json.dumps` |
| Stage 5 (LLM) | ~5.7s | ~84% | HTTPS round-trip to DeepSeek API |
| Stage 6 (Persistence) | ~10ms | <1% | One file write |
| **Total** | **~6.8s** | 100% | LLM call dominates |

The mock provider eliminates the 5.7s LLM call → total drops to ~1.1s, all in kubectl subprocess overhead. This is why the mock is useful for local dev: you can iterate on the pipeline without paying the LLM latency tax.

---

## Guides

### Guide A — Reproduce this exact trace on your machine

```bash
# 1. Clone + install
git clone https://github.com/1hirak/k8s-llm-incident-analyser.git
cd k8s-llm-incident-analyser
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 2. Start minikube and load images
minikube start
eval $(minikube docker-env)
docker build -t demo-app:latest ./demo-app
docker build -t analyser:latest .

# 3. Apply base + analyser
kubectl apply -f k8s/base/
kubectl apply -f k8s/analyser/
kubectl rollout status deployment/demo-app -n demo

# 4. Port-forward the analyser
kubectl port-forward -n demo svc/analyser-svc 8000:80 &

# 5. Inject the 05-oom fault
./scripts/run_scenario.sh 05-oom

# 6. Trigger the OOM by hitting the demo app
kubectl port-forward -n demo svc/demo-app-svc 8001:80 &
curl http://localhost:8001/fault/oom   # pod will be killed

# 7. Wait ~30s for restarts to register
kubectl get pods -n demo -w   # Ctrl-C once Restart Count > 0

# 8. Run the analysis (mock provider, no API key needed)
curl -X POST http://localhost:8000/analyse/pod/demo/demo-app | jq .

# 9. Inspect the persisted report
ls reports/
curl http://localhost:8000/reports | jq .

# 10. Run the evaluation harness against the baselines
python -m evaluation.harness --classifier keyword --scenarios 05-oom
python -m evaluation.harness --classifier rulebased --scenarios 05-oom

# 11. Run against the real LLM (requires DEEPSEEK_API_KEY)
export LLM_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-...
python -m evaluation.harness --classifier llm --scenarios 05-oom

# 12. Reset
./scripts/run_scenario.sh reset
```

### Guide B — Add a new fault scenario using 05-oom as a template

Suppose you want to add `11-cpu-throttle` that exercises a CPU limit instead of memory.

#### Step 1 — Create the fault YAML

```bash
mkdir k8s/scenarios/11-cpu-throttle
```

`k8s/scenarios/11-cpu-throttle/fault.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-app
  namespace: demo
spec:
  template:
    spec:
      containers:
      - name: demo-app
        resources:
          limits:
            cpu: "10m"        # 0.01 CPU — extreme throttling
            memory: "128Mi"
          requests:
            cpu: "10m"
            memory: "64Mi"
```

#### Step 2 — Add a fault endpoint to the demo app (optional)

Edit `demo-app/app/main.py` and add:

```python
@app.get("/fault/cpu")
def fault_cpu():
    end = time.time() + 30
    while time.time() < end:
        _ = sum(i * i for i in range(10_000))   # busy-wait
    return {"done": True}
```

Rebuild: `docker build -t demo-app:latest ./demo-app` (in minikube's docker-env).

#### Step 3 — Create the ground truth file

`evaluation/ground_truth/11-cpu-throttle.json`:

```json
{
  "scenario_id": "11-cpu-throttle",
  "description": "CPU limit reduced to 10m causing severe throttling under load",
  "true_root_cause": "Container CPU limit too low; kernel throttles CPU causing unresponsive app",
  "true_affected_component": "demo-app",
  "true_failure_category": "resource",
  "true_severity": "medium",
  "expected_log_patterns": ["throttled", "cpu"],
  "expected_event_reasons": ["Failed"],
  "correct_remediation_keywords": ["cpu", "limit", "resources", "throttle", "deployment"],
  "notes": "Requires /fault/cpu endpoint to be hit. Liveness probe may fail due to throttling."
}
```

#### Step 4 — Add a fixture for unit tests

Append to `tests/fixtures/scenario_evidence.py`:

```python
def scenario_11_cpu_throttle() -> EvidencePackage:
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs="WARNING CPU throttled",
        pod_status_summary=(
            "Containers:\n  demo-app:\n    State: Running\n"
            "    Ready: False\n    Restart Count: 1\n"
            "Events:\n  Warning Unhealthy  Liveness probe failed"
        ),
        k8s_events_filtered="Warning Unhealthy: Liveness probe failed",
        restart_count=1,
    )

_SCENARIOS.append("11-cpu-throttle")
_FIXTURES["11-cpu-throttle"] = scenario_11_cpu_throttle
TRUE_CATEGORIES["11-cpu-throttle"] = "resource"
```

#### Step 5 — Add keyword/rule-based signals (optional)

If you want the baselines to detect this, add `"cpu throttling": 2` to the `resource` tier in `evaluation/baselines/keyword.py:91`, and extend `_resource_rule` in `evaluation/baselines/rulebased.py:91` to check for `throttled`.

#### Step 6 — Verify

```bash
make test                # all existing tests still pass + new fixture is picked up
./scripts/run_scenario.sh 11-cpu-throttle
curl -X POST http://localhost:8000/analyse/pod/demo/demo-app | jq .
python -m evaluation.harness --classifier llm --scenarios 11-cpu-throttle
```

### Guide C — Swap LLM providers without touching pipeline code

The provider is selected purely by env var. No code changes needed.

| Goal | Command |
|------|---------|
| Use mock (default, no API key) | `export LLM_PROVIDER=mock` |
| Use OpenAI GPT-4o-mini | `export LLM_PROVIDER=openai && export OPENAI_API_KEY=sk-...` |
| Use OpenAI GPT-4o (different model) | `export LLM_PROVIDER=openai && export OPENAI_API_KEY=sk-... && export LLM_MODEL=gpt-4o` |
| Use Anthropic Claude Haiku | `export LLM_PROVIDER=anthropic && export ANTHROPIC_API_KEY=sk-ant-...` |
| Use DeepSeek | `export LLM_PROVIDER=deepseek && export DEEPSEEK_API_KEY=sk-...` |
| Increase response token budget | `export LLM_MAX_TOKENS=4000` |
| Verify which provider is live | `curl http://localhost:8000/health` → `{"status":"ok","provider":"deepseek"}` |

For docker-compose deployments, set these in `.env` (see `.env.example`).

### Guide D — Debug a misclassification

If the analyser returns `failure_category: unknown` for a pod that obviously has a problem:

1. **Inspect what the collector saw.** Add a temporary log to `app/api/analyse.py:27`:
   ```python
   log.info("raw_evidence", current_logs=raw.current_logs[:500],
            pod_status=raw.pod_status[:500], restart_count=raw.restart_count)
   ```

2. **Inspect what the preprocessor produced.** Log the `EvidencePackage` after `preprocessor.process(raw)`:
   ```python
   log.info("evidence_package", pkg=filtered)
   ```

3. **Check whether the signal matched `SIGNAL_PATTERNS`.** Compare the evidence text against the regexes in `app/core/preprocessor.py:13-25`. If the signal word isn't in the list (e.g. a custom app error like `"DB_POOL_EXHAUSTED"`), the preprocessor will drop the line — even if it's the only useful line in the log.

4. **Check the prompt.** Print `build_prompt(filtered)[1]` to see exactly what the LLM received. If the signal isn't in the prompt, the LLM can't use it.

5. **Check the LLM response.** For DeepSeek, log `raw_json` before `IncidentReport.model_validate` (`deepseek_provider.py:65`). For OpenAI/Anthropic, log `message.parsed` / `parsed_output`.

6. **Run the harness on the specific scenario to get metrics.**
   ```bash
   python -m evaluation.harness --classifier llm --scenarios 05-oom
   ```

---

## Key Observations

### What this trace reveals about the architecture

1. **The signal isn't always in the logs.** For 05-oom the only useful signal (`OOMKilled`) lives in `pod_status` and `k8s_events`, not in the application's stdout. The preprocessor's noise filter operates on log text only — it cannot "promote" a signal that isn't there. The architecture compensates by passing the full `pod_status_summary` (truncated to 2000 chars) and the filtered `k8s_events` to the LLM unchanged. **The preprocessor is a noise reducer, not a signal extractor.**

2. **Label-based pod resolution is a real ergonomic win.** The engineer's `curl POST /analyse/pod/demo/demo-app` works even though `demo-app` is a Deployment, not a pod. The collector's fallback to `kubectl get pods -l app=demo-app` (`collector.py:115-119`) saves the engineer from running `kubectl get pods` first.

3. **The redactor is usually a no-op — and that's fine.** For most pod-failure scenarios, the evidence doesn't contain secrets. Redaction is a **defensive control**: it fires only when needed, but it always runs. The cost (~10ms of regex over a few KB) is negligible.

4. **The mock provider is a development accelerator.** It correctly classifies 05-oom as `resource` without any API call, in ~50ms. This lets you iterate on the pipeline (collector, preprocessor, redactor, persistence, API) without paying LLM latency or cost. The qualitative gap (no actionable remediation) is what the evaluation harness exposes.

5. **Structured outputs are the unsung hero.** For OpenAI and Anthropic, the SDK returns a validated `IncidentReport` directly — no `json.loads`, no manual validation, no schema drift. DeepSeek's path is longer (schema in prompt + `model_validate`) because its API doesn't accept a schema field. The Pydantic schema is the contract that makes provider portability possible.

6. **Persistence is best-effort by design.** A disk failure logs a warning but doesn't break the API response. The engineer still gets the diagnosis; only the listing/retrieval endpoints degrade. This is a deliberate resilience choice that prioritises the primary outcome (diagnosis delivered) over the secondary one (report archived).

7. **Evaluation is the differentiator.** Without the ground truth files and the metrics module, "the LLM is better" would be a vibe-claim. With them, you can point to `remediation_keywords_hit: 4/5 (LLM) vs 0/5 (mock)` and say something rigorous. The harness is what turns this from a demo into a research artefact.

### Anti-patterns this codebase avoids

| Anti-pattern | How it's avoided |
|--------------|------------------|
| Shovel raw `kubectl logs` into the LLM | Preprocessor reduces 10K lines to ≤100 with context windows |
| Send secrets to a third-party LLM | Redactor runs before any provider sees the evidence |
| Hardcode one LLM vendor | `BaseLLMProvider` + factory + 4 implementations |
| Trust the LLM's JSON without validation | Pydantic schema is the contract; `ReportValidator` is the safety net |
| Hide evaluation failures | Scenario 10 (wrong-port) is documented as undetectable, not silently dropped |
| Brittle pod-name requirements | Label-based fallback in the collector |
| Persistence failures break the analysis | `save_report` is wrapped in try/except in the API handler |
| LLM invents failure categories | `failure_category` is a Pydantic `Literal[8]` — invalid values raise `ValidationError` |

### What to look at next

| If you want to understand… | Read… |
|---------------------------|-------|
| All 10 scenarios and their fault YAMLs | `k8s/scenarios/*/fault.yaml` |
| The full LLM provider implementations | `app/core/llm/*.py` |
| The baselines in detail | `evaluation/baselines/keyword.py` and `rulebased.py` |
| End-to-end evaluation results across all 10 scenarios | `docs/Technical-Documentation.md` §23 |
| The architecture in survey form | `docs/Technical-Documentation.md` |
| The JSON schema contract | `docs/report_schema.json` |
| How to deploy to AWS EC2 | `docs/Technical-Documentation.md` §21 |

---

*End of deep-dive. Generated 21 July 2026. Companion to [`Technical-Documentation.md`](./Technical-Documentation.md).*
