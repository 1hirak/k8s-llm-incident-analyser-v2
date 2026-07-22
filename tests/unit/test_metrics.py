import json
from pathlib import Path

import pytest
from k8s_llm_shared import EvidenceItem, IncidentReport

from evaluation.metrics import (
    EvaluationResult,
    aggregate,
    evaluate,
    f1_score,
    precision,
    recall,
)


@pytest.fixture
def ground_truth_file(tmp_path: Path) -> Path:
    gt = {
        "scenario_id": "01-missing-env",
        "description": "DATABASE_URL env var removed",
        "true_root_cause": "Missing required environment variable DATABASE_URL",
        "true_affected_component": "demo-app",
        "true_failure_category": "config",
        "true_severity": "critical",
        "expected_log_patterns": ["Missing required configuration", "DATABASE_URL"],
        "expected_event_reasons": ["BackOff"],
        "correct_remediation_keywords": [
            "DATABASE_URL", "environment variable", "ConfigMap", "Secret",
        ],
        "notes": "Confident diagnosis expected.",
    }
    path = tmp_path / "01-missing-env.json"
    path.write_text(json.dumps(gt))
    return path


@pytest.fixture
def valid_report() -> IncidentReport:
    return IncidentReport(
        incident_summary="Pod demo-app failed because DATABASE_URL is missing.",
        likely_root_cause="The DATABASE_URL environment variable is not set.",
        affected_component="demo-app",
        failure_category="config",
        severity="critical",
        confidence=0.9,
        supporting_evidence=[
            EvidenceItem(
                source="pod_log",
                pod="demo-app-abc",
                evidence="FATAL: DATABASE_URL environment variable is not set",
            ),
            EvidenceItem(
                source="kubernetes_event",
                pod="demo-app-abc",
                evidence="Warning BackOff restarting container",
            ),
        ],
        suggested_fix="Set DATABASE_URL in the deployment env or a ConfigMap.",
        recommended_commands=["kubectl describe pod -n demo demo-app-abc"],
        human_verification_steps=["Check environment variables in deployment spec."],
    )


class TestEvaluationResult:
    def test_can_be_created(self):
        r = EvaluationResult(
            scenario_id="01-missing-env",
            root_cause_correct=True,
            category_correct=True,
            schema_valid=True,
            latency_s=1.23,
            confidence=0.9,
            evidence_count=2,
        )
        assert r.scenario_id == "01-missing-env"
        assert r.root_cause_correct is True
        assert r.category_correct is True
        assert r.schema_valid is True
        assert r.latency_s == 1.23
        assert r.confidence == 0.9
        assert r.evidence_count == 2


class TestEvaluate:
    def test_returns_evaluation_result(
        self, valid_report, ground_truth_file
    ):
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert isinstance(result, EvaluationResult)

    def test_category_correct_when_matches(self, valid_report, ground_truth_file):
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.category_correct is True

    def test_category_incorrect_when_mismatch(self, valid_report, ground_truth_file):
        valid_report.failure_category = "network"
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.category_correct is False

    def test_root_cause_correct_when_keywords_match(
        self, valid_report, ground_truth_file
    ):
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.root_cause_correct is True

    def test_root_cause_incorrect_when_no_overlap(
        self, valid_report, ground_truth_file
    ):
        valid_report.likely_root_cause = "The network cable is unplugged."
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.root_cause_correct is False

    def test_schema_valid_is_true_for_valid_report(
        self, valid_report, ground_truth_file
    ):
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.schema_valid is True

    def test_latency_preserved(self, valid_report, ground_truth_file):
        result = evaluate(valid_report, ground_truth_file, latency=2.5)
        assert result.latency_s == 2.5

    def test_confidence_preserved(self, valid_report, ground_truth_file):
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.confidence == 0.9

    def test_evidence_count_matches(self, valid_report, ground_truth_file):
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.evidence_count == 2

    def test_scenario_id_from_ground_truth(self, valid_report, ground_truth_file):
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.scenario_id == "01-missing-env"

    def test_remediation_keywords_present(self, valid_report, ground_truth_file):
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.remediation_keywords_hit >= 2

    def test_remediation_keywords_zero_when_absent(
        self, valid_report, ground_truth_file
    ):
        valid_report.suggested_fix = "Restart the pod and hope for the best."
        valid_report.recommended_commands = ["kubectl restart pod demo-app"]
        valid_report.human_verification_steps = ["Watch the pod come back up."]
        result = evaluate(valid_report, ground_truth_file, latency=0.5)
        assert result.remediation_keywords_hit == 0


class TestAggregateMetrics:
    @pytest.fixture
    def results(self):
        return [
            EvaluationResult(
                scenario_id="01", root_cause_correct=True, category_correct=True,
                schema_valid=True, latency_s=1.0, confidence=0.9, evidence_count=2,
                remediation_keywords_hit=3,
            ),
            EvaluationResult(
                scenario_id="02", root_cause_correct=True, category_correct=False,
                schema_valid=True, latency_s=2.0, confidence=0.8, evidence_count=1,
                remediation_keywords_hit=1,
            ),
            EvaluationResult(
                scenario_id="03", root_cause_correct=False, category_correct=True,
                schema_valid=True, latency_s=3.0, confidence=0.7, evidence_count=3,
                remediation_keywords_hit=0,
            ),
        ]

    def test_precision_returns_float(self, results):
        p = precision(results, attribute="category_correct")
        assert isinstance(p, float)

    def test_precision_correct_value(self, results):
        p = precision(results, attribute="category_correct")
        assert p == pytest.approx(2 / 3, rel=1e-3)

    def test_recall_same_as_precision_when_all_evaluated(self, results):
        r = recall(results, attribute="category_correct")
        assert r == pytest.approx(2 / 3, rel=1e-3)

    def test_f1_score(self, results):
        f = f1_score(results, attribute="category_correct")
        assert f == pytest.approx(2 / 3, rel=1e-3)

    def test_f1_zero_when_no_correct(self, results):
        for r in results:
            r.category_correct = False
        f = f1_score(results, attribute="category_correct")
        assert f == 0.0

    def test_aggregate_returns_summary_dict(self, results):
        summary = aggregate(results)
        assert isinstance(summary, dict)
        assert "n" in summary
        assert summary["n"] == 3
        assert "category_accuracy" in summary
        assert "root_cause_accuracy" in summary
        assert "schema_valid_rate" in summary
        assert "mean_latency_s" in summary
        assert "mean_confidence" in summary
        assert "mean_evidence_count" in summary

    def test_aggregate_mean_latency(self, results):
        summary = aggregate(results)
        assert summary["mean_latency_s"] == pytest.approx(2.0, rel=1e-3)

    def test_aggregate_category_accuracy(self, results):
        summary = aggregate(results)
        assert summary["category_accuracy"] == pytest.approx(2 / 3, rel=1e-3)

    def test_aggregate_empty_list(self):
        summary = aggregate([])
        assert summary["n"] == 0
        assert summary["mean_latency_s"] == 0.0
