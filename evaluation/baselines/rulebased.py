"""Rule-based baseline classifier for Kubernetes incident analysis.

This baseline applies structured rules combining multiple signals (log text,
pod status, restart count, events, container state reasons) in priority order.
It is more sophisticated than the keyword baseline but still requires no LLM
API calls.

Priority order (first matching rule wins):
    image > resource > config > dependency > probe > crash > network

Rationale:
- image and resource have unambiguous k8s state reasons (ImagePullBackOff,
  OOMKilled) and are checked first.
- config and dependency are root-cause categories that, when present, should
  override probe/crash symptoms (e.g. readiness probe failing because the
  database is unreachable → dependency, not probe).
- probe is checked before crash because a liveness-probe timeout with
  restarts is a probe issue, not a code crash.
- crash is checked before network because CrashLoopBackOff with a traceback
  or StartError is a crash, not a network issue.
- network is last because network issues (wrong service targetPort) rarely
  produce error signals in pod evidence alone.
"""

import re

from k8s_llm_shared import EvidencePackage

_PRIORITY = [
    "image",
    "resource",
    "config",
    "dependency",
    "probe",
    "crash",
    "network",
]

_REASON_RE = re.compile(r"reason:\s*(\S+)", re.IGNORECASE)
_MESSAGE_RE = re.compile(r"message:\s*(.+)", re.IGNORECASE)
_LAST_STATE_REASON_RE = re.compile(
    r"last state:.*?reason:\s*(\S+)", re.IGNORECASE | re.DOTALL
)


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(p in text for p in patterns)


def _extract_reasons(pod_status: str) -> str:
    """Extract all 'Reason: X' values from pod describe output."""
    return " ".join(m.group(1).lower() for m in _REASON_RE.finditer(pod_status))


def _extract_last_state_reason(pod_status: str) -> str:
    """Extract the Last State reason from pod describe output."""
    m = _LAST_STATE_REASON_RE.search(pod_status)
    return m.group(1).lower() if m else ""


def _extract_last_state_message(pod_status: str) -> str:
    """Extract the Last State message from pod describe output."""
    msg_re = re.compile(
        r"last state:.*?message:\s*(.+?)(?:\n\s*\n|\n\s+[A-Z]|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    m = msg_re.search(pod_status)
    return m.group(1).strip().lower() if m else ""


def _image_rule(pkg: EvidencePackage, text: str) -> bool:
    reasons = _extract_reasons(pkg.pod_status_summary)
    if _matches_any(reasons, ["imagepullbackoff", "errimagepull"]):
        return True
    if _matches_any(
        text,
        [
            "imagepullbackoff",
            "errimagepull",
            "pull access denied",
            "imagenotfound",
            "manifest not found",
            "failed to pull image",
            "back-off pulling image",
        ],
    ):
        return True
    return False


def _resource_rule(pkg: EvidencePackage, text: str) -> bool:
    reasons = _extract_reasons(pkg.pod_status_summary)
    if _matches_any(reasons, ["oomkilled", "evicted"]):
        return True
    if _matches_any(
        text,
        ["oomkilled", "memory limit", "out of memory", "evicted", "exit code: 137"],
    ):
        return True
    if "memory" in pkg.pod_status_summary.lower() and pkg.restart_count > 0:
        return True
    if "killing" in pkg.k8s_events_filtered.lower() and "oom" in text:
        return True
    return False


def _config_rule(pkg: EvidencePackage, text: str) -> bool:
    if _matches_any(text, ["missing required", "environment variable", "not set"]):
        return True
    if "keyerror" in text:
        return True
    if _matches_any(text, ["configmap", "log_level"]) and _matches_any(
        text, ["invalid", "not set", "missing"]
    ):
        return True
    if "configuration" in text and pkg.restart_count > 0:
        return True
    return False


def _dependency_rule(pkg: EvidencePackage, text: str) -> bool:
    if _matches_any(
        text,
        [
            "connection refused",
            "no route to host",
            "name resolution",
            "unreachable",
            "connection timeout",
            "database connection",
        ],
    ):
        return True
    if "timeout" in text and pkg.restart_count > 0:
        return True
    if "database" in text and ("refused" in text or "unreachable" in text):
        return True
    return False


def _probe_rule(pkg: EvidencePackage, text: str) -> bool:
    events = pkg.k8s_events_filtered.lower()
    if _matches_any(
        events,
        [
            "readiness probe",
            "liveness probe",
            "probe failed",
            "probe timed out",
        ],
    ):
        return True
    if _matches_any(events, ["readinessprobefailed", "livenessprobefailed"]):
        return True
    if "unhealthy" in events and _matches_any(
        text, ["readiness probe", "liveness probe", "probe failed", "http probe"]
    ):
        return True
    # Ready=False with no restarts and no other root-cause signals
    if "ready: false" in pkg.pod_status_summary.lower() and pkg.restart_count == 0:
        return True
    return False


def _network_rule(pkg: EvidencePackage, text: str) -> bool:
    if _matches_any(
        text,
        [
            "address already in use",
            "port already in use",
            "no such host",
            "network unreachable",
            "no endpoints",
        ],
    ):
        return True
    if "connection reset" in text and "port" in text:
        return True
    return False


def _crash_rule(pkg: EvidencePackage, text: str) -> bool:
    last_reason = _extract_last_state_reason(pkg.pod_status_summary)
    last_msg = _extract_last_state_message(pkg.pod_status_summary)
    if _matches_any(last_reason, ["containercannotrun", "starterror"]):
        return True
    if _matches_any(last_msg, ["executable file not found", "no such file or directory"]):
        return True
    if _matches_any(
        text, ["traceback", "runtimeerror", "zerodivision", "segfault", "panic"]
    ):
        return True
    if "startup_fault" in text:
        return True
    if "exception" in text and pkg.restart_count > 3:
        return True
    if "crashloopbackoff" in text and pkg.restart_count > 2:
        return True
    return False


_RULES = {
    "image": _image_rule,
    "resource": _resource_rule,
    "config": _config_rule,
    "dependency": _dependency_rule,
    "probe": _probe_rule,
    "network": _network_rule,
    "crash": _crash_rule,
}


def _all_text(pkg: EvidencePackage) -> str:
    return " ".join(
        [
            pkg.current_logs,
            pkg.previous_logs,
            pkg.k8s_events_filtered,
            pkg.pod_status_summary,
        ]
    ).lower()


def rule_classify(package: EvidencePackage) -> str:
    """Classify an incident using structured rules. First matching rule wins."""
    text = _all_text(package)
    for category in _PRIORITY:
        if _RULES[category](package, text):
            return category
    return "unknown"


def rule_classify_detailed(package: EvidencePackage) -> dict:
    """Return category, matched rule, and all triggered signals."""
    text = _all_text(package)
    triggered = []
    for category in _PRIORITY:
        if _RULES[category](package, text):
            triggered.append(category)
    if not triggered:
        return {
            "failure_category": "unknown",
            "confidence": 0.0,
            "matched_rule": "unknown",
            "triggered_rules": [],
        }
    confidence = min(0.85, 0.5 + 0.1 * len(triggered))
    return {
        "failure_category": triggered[0],
        "confidence": round(confidence, 2),
        "matched_rule": triggered[0],
        "triggered_rules": triggered,
    }


class RuleBasedClassifier:
    """Object-oriented wrapper around rule_classify with explanation support."""

    def classify(self, package: EvidencePackage) -> str:
        return rule_classify(package)

    def classify_detailed(self, package: EvidencePackage) -> dict:
        return rule_classify_detailed(package)

    def explain(self, package: EvidencePackage) -> dict:
        text = _all_text(package)
        signals = []
        for category in _PRIORITY:
            if _RULES[category](package, text):
                signals.append(category)
        last_reason = _extract_last_state_reason(package.pod_status_summary)
        return {
            "matched_rule": signals[0] if signals else "unknown",
            "evidence_signals": signals,
            "restart_count": package.restart_count,
            "last_state_reason": last_reason or "none",
        }
