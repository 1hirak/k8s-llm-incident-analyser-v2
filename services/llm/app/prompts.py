from k8s_llm_shared import EvidencePackage

PROMPT_VERSION = "2"

SYSTEM_PROMPT = """
You are a Kubernetes incident analyst. Your task is to analyse the provided
diagnostic evidence from a Kubernetes environment and produce a structured
incident report.

Rules:
- Only use evidence that is present in the provided data.
- Do not invent log lines or events that were not given.
- Make likely_root_cause descriptive: explain the failure mechanism in 2-4
  sentences and connect it to the relevant logs, status, or events.
- Populate analysis_explanation with a concise, evidence-backed rationale,
  1-5 observable key signals, and an honest uncertainty statement.
- Do not reveal hidden chain-of-thought or private deliberation. The rationale
  must be a short audit explanation that an operator can verify from the cited evidence.
- Set confidence lower if evidence is ambiguous or incomplete.
- Never recommend automated remediation or arbitrary shell execution. When a safe typed action is clear,
  populate recommended_actions using only the bounded action types in the schema;
  otherwise return an empty list. Every action still requires operator approval.
- Respond ONLY with a valid JSON object matching the schema below.
""".strip()

USER_PROMPT_TEMPLATE = """
=== KUBERNETES DIAGNOSTIC EVIDENCE ===

Namespace: {namespace}
Target: {target_kind}/{target}
Related pods: {pod_names}

--- POD STATUS ---
{pod_status}

--- TARGET CONTEXT ---
{target_context}

--- APPLICATION LOGS (current) ---
{current_logs}

--- APPLICATION LOGS (previous container, if available) ---
{previous_logs}

--- KUBERNETES EVENTS ---
{k8s_events}

--- RESTART COUNT ---
{restart_count}

Analyse the evidence above and return a JSON object matching the schema in the
system instructions.
For analysis_explanation, provide a concise audit explanation rather than hidden
reasoning. The input_summary will be added by the analysis service.
""".strip()


def build_prompt(package: EvidencePackage) -> tuple[str, str]:
    user_prompt = USER_PROMPT_TEMPLATE.format(
        namespace=package.namespace,
        target=package.pod_name,
        target_kind=package.target_kind,
        pod_names=", ".join(package.pod_names) or "(none)",
        pod_status=package.pod_status_summary or "(no pod status available)",
        target_context=package.target_context or "(no target context available)",
        current_logs=package.current_logs or "(no current logs)",
        previous_logs=package.previous_logs or "(no previous logs)",
        k8s_events=package.k8s_events_filtered or "(no kubernetes events)",
        restart_count=package.restart_count,
    )

    return SYSTEM_PROMPT, user_prompt
