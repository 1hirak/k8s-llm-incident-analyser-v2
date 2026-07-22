"""Evaluation harness for the Kubernetes incident analyser.

The harness orchestrates running fault scenarios against a classifier
(LLM provider or baseline) and scoring the results against ground truth.

All dependencies (collector, preprocessor, redactor) are injected so the
harness can be tested without a real Kubernetes cluster. In production
use, the injected dependencies are the HTTP adapters from
evaluation/services.py, which call the microservices stack.
"""
import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol, Union

from k8s_llm_shared import EvidencePackage, IncidentReport, RawEvidence

from evaluation.metrics import EvaluationResult, evaluate


class Collector(Protocol):
    def collect(self, namespace: str, pod_name: str) -> RawEvidence: ...


class Preprocessor(Protocol):
    def process(self, evidence: RawEvidence) -> EvidencePackage: ...


class Redactor(Protocol):
    def redact(self, package: EvidencePackage) -> EvidencePackage: ...

SCENARIOS = [
    "01-missing-env",
    "02-db-unavailable",
    "03-crashloop",
    "04-imagepull",
    "05-oom",
    "06-readiness",
    "07-liveness",
    "08-bad-configmap",
    "09-app-exception",
    "10-wrong-port",
]

DEFAULT_GT_DIR = Path(__file__).parent / "ground_truth"

ClassifierFn = Callable[[EvidencePackage], Union[IncidentReport, dict, Awaitable[IncidentReport]]]


def _make_report_from_dict(data: dict) -> IncidentReport:
    return IncidentReport(
        incident_summary=data.get("incident_summary", "Baseline classification."),
        likely_root_cause=data.get("likely_root_cause", data.get("failure_category", "unknown")),
        affected_component=data.get("affected_component", "demo-app"),
        failure_category=data["failure_category"],
        severity=data.get("severity", "medium"),
        confidence=float(data.get("confidence", 0.5)),
        supporting_evidence=data.get(
            "supporting_evidence",
            [{"source": "pod_log", "pod": "demo-app", "evidence": "(baseline)"}],
        ),
        suggested_fix=data.get("suggested_fix", "(baseline) Investigate the reported category."),
        recommended_commands=data.get(
            "recommended_commands", ["kubectl describe pod -n demo demo-app"]
        ),
        human_verification_steps=data.get(
            "human_verification_steps", ["Inspect the pod manually."]
        ),
    )


_BASELINE_ROOT_CAUSES = {
    "config": "Missing or invalid configuration in deployment environment or ConfigMap.",
    "dependency": "Dependent service (database or external API) is unreachable or refusing connections.",
    "crash": "Container crashed due to application error, invalid command, or unhandled exception.",
    "image": "Kubernetes cannot pull the container image — wrong tag, missing registry, or access denied.",
    "resource": "Container exceeded memory or CPU limit and was killed by the kernel.",
    "probe": "Readiness or liveness probe is failing — wrong path, timeout, or unhealthy endpoint.",
    "network": "Network configuration mismatch — wrong port, service targetPort, or address in use.",
    "unknown": "No specific failure pattern matched in the collected evidence.",
}

_BASELINE_FIXES = {
    "config": "Check environment variables and ConfigMap values in the deployment spec.",
    "dependency": "Verify the dependent service is running and reachable from the pod network.",
    "crash": "Inspect previous container logs for the stack trace or startup error message.",
    "image": "Verify the image tag exists in the registry and imagePullPolicy is correct.",
    "resource": "Increase memory/CPU limits in the deployment resource spec.",
    "probe": "Check the probe path, port, and timeout in the deployment spec.",
    "network": "Verify the Service targetPort matches the container port.",
    "unknown": "Run kubectl describe pod and kubectl get events for manual diagnosis.",
}

_BASELINE_COMMANDS = {
    "config": ["kubectl get configmap -n demo", "kubectl describe deployment demo-app -n demo"],
    "dependency": ["kubectl get svc -n demo", "kubectl exec -n demo demo-app -- nslookup database"],
    "crash": ["kubectl logs -n demo demo-app --previous", "kubectl describe pod -n demo demo-app"],
    "image": ["kubectl describe pod -n demo demo-app", "kubectl get events -n demo"],
    "resource": ["kubectl describe pod -n demo demo-app", "kubectl top pod -n demo"],
    "probe": ["kubectl describe pod -n demo demo-app", "kubectl get events -n demo"],
    "network": ["kubectl get svc -n demo", "kubectl get endpoints -n demo"],
    "unknown": ["kubectl describe pod -n demo demo-app", "kubectl get events -n demo"],
}


def classify_with_baseline(
    package: EvidencePackage, baseline_fn: Any
) -> dict:
    """Run a baseline classifier and return a report-shaped dict.

    If *baseline_fn* exposes a ``classify_detailed`` method (as the improved
    KeywordClassifier and RuleBasedClassifier do), use it to produce a
    richer report with confidence and matched signals.
    """
    detailed_fn = getattr(baseline_fn, "classify_detailed", None)
    if detailed_fn is not None:
        detail = detailed_fn(package)
        category = detail["failure_category"]
        confidence = detail.get("confidence", 0.5)
        matched = detail.get("matched_keywords", [])
        signals = detail.get("matched_rule", "")
        root_cause = _BASELINE_ROOT_CAUSES.get(category, _BASELINE_ROOT_CAUSES["unknown"])
        if matched:
            kw_list = ", ".join(m["keyword"] for m in matched[:3])
            root_cause = f"{root_cause} Matched signals: {kw_list}."
        elif signals and signals != "unknown":
            root_cause = f"{root_cause} Triggered rule: {signals}."
        return {
            "failure_category": category,
            "likely_root_cause": root_cause,
            "confidence": confidence,
            "suggested_fix": _BASELINE_FIXES.get(category, _BASELINE_FIXES["unknown"]),
            "recommended_commands": _BASELINE_COMMANDS.get(
                category, _BASELINE_COMMANDS["unknown"]
            ),
        }
    category = baseline_fn(package)
    return {
        "failure_category": category,
        "likely_root_cause": _BASELINE_ROOT_CAUSES.get(category, _BASELINE_ROOT_CAUSES["unknown"]),
        "confidence": 0.5,
        "suggested_fix": _BASELINE_FIXES.get(category, _BASELINE_FIXES["unknown"]),
        "recommended_commands": _BASELINE_COMMANDS.get(category, _BASELINE_COMMANDS["unknown"]),
    }


async def classify_with_llm(package: EvidencePackage, provider) -> IncidentReport:
    """Run an LLM provider and return a validated IncidentReport."""
    return await provider.analyse(package)


async def run_scenario(
    scenario_id: str,
    namespace: str,
    pod_name: str,
    collector: Collector,
    preprocessor: Preprocessor,
    redactor: Redactor,
    classifier: ClassifierFn,
    gt_path: Path,
) -> EvaluationResult:
    """Run a single scenario: collect -> preprocess -> redact -> classify -> score."""
    t0 = time.monotonic()
    raw = collector.collect(namespace, pod_name)
    filtered = preprocessor.process(raw)
    safe = redactor.redact(filtered)

    outcome = classifier(safe)
    if asyncio.iscoroutine(outcome):
        outcome = await outcome

    latency = time.monotonic() - t0

    if isinstance(outcome, IncidentReport):
        report = outcome
    elif isinstance(outcome, dict):
        report = _make_report_from_dict(outcome)
    else:
        raise TypeError(f"Classifier returned unsupported type: {type(outcome)}")

    return evaluate(report, gt_path, latency)


def save_results(results: list[EvaluationResult], path: Path) -> None:
    path.write_text(json.dumps([asdict(r) for r in results], indent=2))


class EvaluationHarness:
    """Orchestrates running multiple scenarios with shared dependencies."""

    def __init__(
        self,
        collector: Collector,
        preprocessor: Preprocessor,
        redactor: Redactor,
        gt_dir: Path = DEFAULT_GT_DIR,
    ):
        self.collector = collector
        self.preprocessor = preprocessor
        self.redactor = redactor
        self.gt_dir = gt_dir

    async def run_all(
        self,
        scenarios: list[str] | None = None,
        namespace: str = "demo",
        pod_name: str = "demo-app",
        classifier: ClassifierFn | None = None,
    ) -> list[EvaluationResult]:
        if scenarios is None:
            scenarios = SCENARIOS
        if classifier is None:
            from evaluation.services import ServiceLLMProvider
            provider = ServiceLLMProvider()
            classifier = lambda pkg: classify_with_llm(pkg, provider)  # noqa: E731

        results: list[EvaluationResult] = []
        for scenario_id in scenarios:
            gt_path = self.gt_dir / f"{scenario_id}.json"
            if not gt_path.exists():
                continue
            result = await run_scenario(
                scenario_id=scenario_id,
                namespace=namespace,
                pod_name=pod_name,
                collector=self.collector,
                preprocessor=self.preprocessor,
                redactor=self.redactor,
                classifier=classifier,
                gt_path=gt_path,
            )
            results.append(result)
        return results


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run evaluation scenarios against a classifier"
    )
    parser.add_argument(
        "--classifier",
        choices=["llm", "keyword", "rulebased"],
        default="llm",
        help="Classifier to use (default: llm)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=None,
        help="Subset of scenario IDs to run (default: all)",
    )
    parser.add_argument(
        "--namespace",
        default="demo",
        help="Kubernetes namespace (default: demo)",
    )
    parser.add_argument(
        "--pod-name",
        default="demo-app",
        help="Pod name prefix (default: demo-app)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path (default: evaluation/results_{classifier}.json)",
    )
    args = parser.parse_args()

    from evaluation.services import (
        PassThroughRedactor,
        ServiceCollector,
        ServiceLLMProvider,
        ServicePreprocessor,
    )

    collector = ServiceCollector()
    preprocessor = ServicePreprocessor()
    redactor = PassThroughRedactor()
    harness = EvaluationHarness(collector, preprocessor, redactor)

    if args.classifier == "llm":
        provider = ServiceLLMProvider()
        classifier = lambda pkg: classify_with_llm(pkg, provider)  # noqa: E731
    elif args.classifier == "keyword":
        from evaluation.baselines.keyword import KeywordClassifier
        kw = KeywordClassifier()
        classifier = lambda pkg: classify_with_baseline(pkg, kw)  # noqa: E731
    elif args.classifier == "rulebased":
        from evaluation.baselines.rulebased import RuleBasedClassifier
        rb = RuleBasedClassifier()
        classifier = lambda pkg: classify_with_baseline(pkg, rb)  # noqa: E731
    else:
        raise ValueError(f"Unknown classifier: {args.classifier}")

    results = await harness.run_all(
        scenarios=args.scenarios,
        namespace=args.namespace,
        pod_name=args.pod_name,
        classifier=classifier,
    )

    output_path = Path(
        args.output or f"evaluation/results_{args.classifier}.json"
    )
    save_results(results, output_path)
    print(f"Saved {len(results)} results to {output_path}")
    from evaluation.metrics import aggregate
    summary = aggregate(results)
    print(f"Summary: {json.dumps(summary, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
