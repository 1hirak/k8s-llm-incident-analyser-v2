import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from k8s_llm_shared import IncidentReport
from pydantic import ValidationError


@dataclass
class EvaluationResult:
    scenario_id: str
    root_cause_correct: bool
    category_correct: bool
    schema_valid: bool
    latency_s: float
    confidence: float
    evidence_count: int
    remediation_keywords_hit: int = 0


def _root_cause_matches(report_cause: str, true_cause: str) -> bool:
    report_words = {w for w in report_cause.lower().split() if len(w) > 4}
    true_words = {w for w in true_cause.lower().split() if len(w) > 4}
    return bool(report_words & true_words)


def _remediach_hits(report: IncidentReport, gt: dict) -> int:
    haystack = " ".join(
        [
            report.suggested_fix,
            " ".join(report.recommended_commands),
            " ".join(report.human_verification_steps),
        ]
    ).lower()
    return sum(
        1 for kw in gt.get("correct_remediation_keywords", []) if kw.lower() in haystack
    )


def _schema_round_trips(report: IncidentReport) -> bool:
    """A report is schema-valid if its dump re-validates against the model."""
    try:
        IncidentReport.model_validate(report.model_dump())
    except ValidationError:
        return False
    return True


def evaluate(
    report: IncidentReport, ground_truth_path: Path, latency: float
) -> EvaluationResult:
    gt = json.loads(ground_truth_path.read_text())
    return EvaluationResult(
        scenario_id=gt["scenario_id"],
        root_cause_correct=_root_cause_matches(
            report.likely_root_cause, gt["true_root_cause"]
        ),
        category_correct=report.failure_category == gt["true_failure_category"],
        schema_valid=_schema_round_trips(report),
        latency_s=latency,
        confidence=report.confidence,
        evidence_count=len(report.supporting_evidence),
        remediation_keywords_hit=_remediach_hits(report, gt),
    )


def precision(results: Iterable[EvaluationResult], attribute: str) -> float:
    """Fraction of evaluated scenarios where the given boolean attribute is True."""
    results = list(results)
    if not results:
        return 0.0
    correct = sum(1 for r in results if getattr(r, attribute))
    return correct / len(results)


def recall(results: Iterable[EvaluationResult], attribute: str) -> float:
    """Equivalent to precision when every scenario has been evaluated."""
    return precision(results, attribute)


def f1_score(results: Iterable[EvaluationResult], attribute: str) -> float:
    """Harmonic mean of precision and recall. Equal to accuracy when p == r."""
    p = precision(results, attribute)
    r = recall(results, attribute)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def aggregate(results: Iterable[EvaluationResult]) -> dict:
    results = list(results)
    n = len(results)
    if n == 0:
        return {
            "n": 0,
            "category_accuracy": 0.0,
            "root_cause_accuracy": 0.0,
            "schema_valid_rate": 0.0,
            "mean_latency_s": 0.0,
            "mean_confidence": 0.0,
            "mean_evidence_count": 0.0,
            "mean_remediation_keywords_hit": 0.0,
        }
    return {
        "n": n,
        "category_accuracy": precision(results, "category_correct"),
        "root_cause_accuracy": precision(results, "root_cause_correct"),
        "schema_valid_rate": precision(results, "schema_valid"),
        "mean_latency_s": sum(r.latency_s for r in results) / n,
        "mean_confidence": sum(r.confidence for r in results) / n,
        "mean_evidence_count": sum(r.evidence_count for r in results) / n,
        "mean_remediation_keywords_hit": sum(
            r.remediation_keywords_hit for r in results
        ) / n,
    }


def results_to_json(results: Iterable[EvaluationResult], path: Path) -> None:
    path.write_text(
        json.dumps([asdict(r) for r in results], indent=2)
    )
