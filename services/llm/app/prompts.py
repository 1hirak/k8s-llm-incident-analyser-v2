import json
from datetime import datetime, timezone

from k8s_llm_shared import EvidencePackage, IncidentReport

SYSTEM_PROMPT = """
You are a Kubernetes incident analyst. Your task is to analyse the provided
diagnostic evidence from a Kubernetes environment and produce a structured
incident report.

Rules:
- Only use evidence that is present in the provided data.
- Do not invent log lines or events that were not given.
- Set confidence lower if evidence is ambiguous or incomplete.
- Never recommend automated remediation -- suggest human-verifiable steps only.
- Respond ONLY with a valid JSON object matching the schema below.
""".strip()

USER_PROMPT_TEMPLATE = """
=== KUBERNETES DIAGNOSTIC EVIDENCE ===

Namespace: {namespace}
Target: {target}
Collection Time: {timestamp}

--- POD STATUS ---
{pod_status}

--- APPLICATION LOGS (current) ---
{current_logs}

--- APPLICATION LOGS (previous container, if available) ---
{previous_logs}

--- KUBERNETES EVENTS ---
{k8s_events}

--- RESTART COUNT ---
{restart_count}

=== REQUIRED OUTPUT SCHEMA ===
{json_schema}

Analyse the evidence above and return a JSON object matching the schema.
""".strip()


def build_prompt(package: EvidencePackage) -> tuple[str, str]:
    schema_json = json.dumps(IncidentReport.model_json_schema(), indent=2)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        namespace=package.namespace,
        target=package.pod_name,
        timestamp=datetime.now(timezone.utc).isoformat(),
        pod_status=package.pod_status_summary or "(no pod status available)",
        current_logs=package.current_logs or "(no current logs)",
        previous_logs=package.previous_logs or "(no previous logs)",
        k8s_events=package.k8s_events_filtered or "(no kubernetes events)",
        restart_count=package.restart_count,
        json_schema=schema_json,
    )

    return SYSTEM_PROMPT, user_prompt
