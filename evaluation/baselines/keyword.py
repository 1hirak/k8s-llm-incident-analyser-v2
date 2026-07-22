"""Keyword-based baseline classifier for Kubernetes incident analysis.

This baseline searches evidence text for known keyword patterns associated
with each failure category. It uses weighted scoring: definitive k8s signals
(e.g. "ImagePullBackOff") get weight 3, strong application signals (e.g.
"missing required") get weight 2, and generic/symptom signals (e.g.
"CrashLoopBackOff") get weight 1.

A disambiguation rule ensures that when probe-failure signals (which are
usually symptoms) co-occur with root-cause signals from another category,
the root-cause category wins.
"""
from k8s_llm_shared import EvidencePackage

# Tier 1 — Definitive (weight 3): near-unambiguous k8s/container signals
# Tier 2 — Strong     (weight 2): clear application or event-level signals
# Tier 3 — Weak        (weight 1): generic terms or symptoms that overlap
KEYWORD_WEIGHTS: dict[str, dict[str, int]] = {
    "crash": {
        # Tier 1 — definitive crash signals
        "executable file not found": 3,
        "no such file or directory": 3,
        "containercannotrun": 3,
        "starterror": 3,
        "traceback": 3,
        "runtimeerror": 3,
        "zerodivision": 3,
        "segfault": 3,
        "panic": 3,
        # Tier 2 — strong crash signals
        "startup_fault": 2,
        "unhandled exception": 2,
        "division by zero": 2,
        # Tier 3 — symptom (CrashLoopBackOff is a k8s state, not a root cause)
        "crashloopbackoff": 1,
        "exception": 1,
    },
    "config": {
        # Tier 1 — definitive config signals
        "missing required": 3,
        "environment variable": 3,
        "keyerror": 3,
        # Tier 2 — strong config signals
        "not set": 2,
        "configmap": 2,
        "invalid value": 2,
        "log_level": 2,
        # Tier 3 — generic
        "configuration": 1,
        "invalid": 1,
    },
    "dependency": {
        # Tier 1 — definitive dependency signals
        "no route to host": 3,
        "name resolution": 3,
        "dns": 3,
        # Tier 2 — strong dependency signals
        "connection refused": 2,
        "unreachable": 2,
        "connection timeout": 2,
        "timeout while connecting": 2,
        "database connection": 2,
        # Tier 3 — generic
        "database": 1,
        "timeout": 1,
    },
    "image": {
        # Tier 1 — definitive image signals
        "imagepullbackoff": 3,
        "errimagepull": 3,
        "pull access denied": 3,
        "imagenotfound": 3,
        "manifest not found": 3,
        "failed to pull image": 3,
        # Tier 2 — strong image signals
        "back-off pulling image": 2,
        # Tier 3 — generic
        "manifest": 1,
        "image": 1,
    },
    "resource": {
        # Tier 1 — definitive resource signals
        "oomkilled": 3,
        "out of memory": 3,
        "memory limit": 3,
        "evicted": 3,
        "exit code: 137": 3,
        # Tier 2 — strong resource signals
        "memory allocation": 2,
        "cpu limit": 2,
        "throttled": 2,
        "cpu throttling": 2,
        "signal 9": 2,
        # Tier 3 — generic
        "memory": 1,
    },
    "probe": {
        # Tier 1 — definitive probe event reasons
        "readinessprobefailed": 3,
        "livenessprobefailed": 3,
        # Tier 2 — strong probe signals
        "readiness probe": 2,
        "liveness probe": 2,
        "probe failed": 2,
        "probe timed out": 2,
        "http probe failed": 2,
        # Tier 3 — generic / symptom
        "unhealthy": 1,
        "backoff": 1,
    },
    "network": {
        # Tier 1 — definitive network signals
        "port already in use": 3,
        "address already in use": 3,
        "no such host": 3,
        "network unreachable": 3,
        "no endpoints": 3,
        # Tier 2 — strong network signals
        "connection reset": 2,
        "targetport": 2,
        # Tier 3 — generic
        "connection refused": 1,
    },
}

# Symptom categories that should be deprioritised when root-cause signals
# from another category are present. Probe failures and CrashLoopBackOff
# are symptoms — the underlying root cause is something else.
_SYMPTOM_CATEGORIES = {"probe"}

# Root-cause categories that override symptoms when they have any Tier-1/2 match
_ROOT_CAUSE_CATEGORIES = {"image", "resource", "config", "dependency", "crash", "network"}


def _concatenate_text(package: EvidencePackage) -> str:
    return " ".join(
        [
            package.current_logs,
            package.previous_logs,
            package.k8s_events_filtered,
            package.pod_status_summary,
        ]
    ).lower()


def _weighted_scores(text: str) -> dict[str, float]:
    """Calculate weighted scores for each category."""
    scores: dict[str, float] = {}
    for category, keywords in KEYWORD_WEIGHTS.items():
        total = 0.0
        for kw, weight in keywords.items():
            if kw in text:
                total += weight
        scores[category] = total
    return scores


def _disambiguate(scores: dict[str, float]) -> dict[str, float]:
    """Deprioritise symptom categories when root-cause signals are present.

    If any root-cause category has a score >= 2 (at least one strong signal),
    halve all symptom-category scores. This ensures that e.g. a readiness
    probe failure caused by a missing database (dependency) is classified
    as dependency, not probe.
    """
    root_cause_present = any(
        scores.get(cat, 0) >= 2.0 for cat in _ROOT_CAUSE_CATEGORIES
    )
    if not root_cause_present:
        return scores
    adjusted = dict(scores)
    for cat in _SYMPTOM_CATEGORIES:
        if adjusted.get(cat, 0) > 0:
            adjusted[cat] = adjusted[cat] * 0.5
    return adjusted


def keyword_classify(package: EvidencePackage) -> str:
    """Classify an incident using weighted keyword matching.

    Returns 'unknown' if no match.
    """
    text = _concatenate_text(package)
    scores = _disambiguate(_weighted_scores(text))
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "unknown"


def keyword_classify_detailed(package: EvidencePackage) -> dict:
    """Return category, confidence, and matched keywords."""
    text = _concatenate_text(package)
    raw_scores = _weighted_scores(text)
    scores = _disambiguate(raw_scores)
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return {
            "failure_category": "unknown",
            "confidence": 0.0,
            "matched_keywords": [],
        }
    matched = []
    for kw, weight in KEYWORD_WEIGHTS[best].items():
        if kw in text:
            matched.append({"keyword": kw, "weight": weight})
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
    confidence = min(0.9, scores[best] / (scores[best] + second + 0.5))
    return {
        "failure_category": best,
        "confidence": round(confidence, 2),
        "matched_keywords": matched,
    }


class KeywordClassifier:
    """Object-oriented wrapper around keyword_classify with scoring and detail."""

    def scores(self, package: EvidencePackage) -> dict[str, float]:
        text = _concatenate_text(package)
        return _disambiguate(_weighted_scores(text))

    def raw_scores(self, package: EvidencePackage) -> dict[str, float]:
        text = _concatenate_text(package)
        return _weighted_scores(text)

    def classify(self, package: EvidencePackage) -> str:
        scores = self.scores(package)
        best = max(scores, key=lambda k: scores[k])
        return best if scores[best] > 0 else "unknown"

    def classify_detailed(self, package: EvidencePackage) -> dict:
        return keyword_classify_detailed(package)
