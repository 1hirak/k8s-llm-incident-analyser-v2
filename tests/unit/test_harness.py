"""Tests for the evaluation harness (orchestration only).

The real preprocessing/redaction logic lives in processor-svc and is
covered by its own test suite. Here, lightweight fakes stand in so the
harness's collect → process → redact → classify → score flow is tested
in isolation.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from k8s_llm_shared import (
    EvidenceItem,
    EvidencePackage,
    IncidentReport,
    RawEvidence,
)

from evaluation.baselines.keyword import keyword_classify
from evaluation.baselines.rulebased import rule_classify
from evaluation.harness import (
    EvaluationHarness,
    classify_with_baseline,
    classify_with_llm,
    run_scenario,
    save_results,
)
from evaluation.metrics import EvaluationResult


class FakePreprocessor:
    """Minimal stand-in for processor-svc's preprocessing stage."""

    def process(self, raw: RawEvidence) -> EvidencePackage:
        return EvidencePackage(
            namespace=raw.namespace,
            pod_name=raw.pod_name,
            current_logs=raw.current_logs,
            previous_logs=raw.previous_logs,
            pod_status_summary=raw.pod_status[:2000],
            k8s_events_filtered=raw.k8s_events,
            restart_count=raw.restart_count,
        )


class FakeRedactor:
    def redact(self, package: EvidencePackage) -> EvidencePackage:
        return package


@pytest.fixture
def fake_raw_evidence():
    return RawEvidence(
        namespace="demo",
        pod_name="demo-app-abc",
        current_logs="FATAL: DATABASE_URL environment variable is not set",
        previous_logs="RuntimeError: Missing required configuration",
        pod_status="State: Waiting Reason: CrashLoopBackOff",
        k8s_events="Warning BackOff restarting container",
        restart_count=3,
    )


@pytest.fixture
def fake_report():
    return IncidentReport(
        incident_summary="Pod demo-app failed to start due to missing configuration.",
        likely_root_cause="The DATABASE_URL environment variable is not set.",
        affected_component="demo-app",
        failure_category="config",
        severity="critical",
        confidence=0.9,
        supporting_evidence=[
            EvidenceItem(
                source="pod_log",
                pod="demo-app-abc",
                evidence="FATAL: DATABASE_URL not set",
            )
        ],
        suggested_fix="Set DATABASE_URL in the deployment env or ConfigMap.",
        recommended_commands=["kubectl describe pod -n demo demo-app-abc"],
        human_verification_steps=["Check environment variables in deployment."],
    )


@pytest.fixture
def gt_path(tmp_path: Path) -> Path:
    gt = {
        "scenario_id": "01-missing-env",
        "description": "DATABASE_URL env var removed",
        "true_root_cause": "Missing required environment variable DATABASE_URL",
        "true_affected_component": "demo-app",
        "true_failure_category": "config",
        "true_severity": "critical",
        "expected_log_patterns": ["DATABASE_URL"],
        "expected_event_reasons": ["BackOff"],
        "correct_remediation_keywords": ["DATABASE_URL", "environment variable", "ConfigMap"],
        "notes": "Test scenario.",
    }
    p = tmp_path / "01-missing-env.json"
    p.write_text(json.dumps(gt))
    return p


class TestClassifyWithBaseline:
    def test_returns_dict_with_category(self, fake_raw_evidence):
        pkg = FakePreprocessor().process(fake_raw_evidence)
        result = classify_with_baseline(pkg, keyword_classify)
        assert isinstance(result, dict)
        assert "failure_category" in result
        assert isinstance(result["failure_category"], str)

    def test_keyword_baseline_detects_config(self, fake_raw_evidence):
        pkg = FakePreprocessor().process(fake_raw_evidence)
        result = classify_with_baseline(pkg, keyword_classify)
        assert result["failure_category"] == "config"

    def test_rulebased_baseline_detects_config(self, fake_raw_evidence):
        pkg = FakePreprocessor().process(fake_raw_evidence)
        result = classify_with_baseline(pkg, rule_classify)
        assert result["failure_category"] == "config"


class TestClassifyWithLLM:
    @pytest.mark.asyncio
    async def test_returns_incident_report(self, fake_raw_evidence, fake_report):
        pkg = FakeRedactor().redact(FakePreprocessor().process(fake_raw_evidence))

        provider = MagicMock()
        provider.analyse = AsyncMock(return_value=fake_report)

        result = await classify_with_llm(pkg, provider)
        assert isinstance(result, IncidentReport)
        assert result.failure_category == "config"


class TestRunScenario:
    @pytest.mark.asyncio
    async def test_run_scenario_with_llm_returns_evaluation_result(
        self, fake_raw_evidence, fake_report, gt_path
    ):
        collector = MagicMock()
        collector.collect = MagicMock(return_value=fake_raw_evidence)

        provider = MagicMock()
        provider.analyse = AsyncMock(return_value=fake_report)

        result = await run_scenario(
            scenario_id="01-missing-env",
            namespace="demo",
            pod_name="demo-app-abc",
            collector=collector,
            preprocessor=FakePreprocessor(),
            redactor=FakeRedactor(),
            classifier=lambda pkg: classify_with_llm(pkg, provider),
            gt_path=gt_path,
        )
        assert isinstance(result, EvaluationResult)
        assert result.scenario_id == "01-missing-env"
        assert result.category_correct is True
        assert result.schema_valid is True

    @pytest.mark.asyncio
    async def test_run_scenario_with_baseline(
        self, fake_raw_evidence, gt_path
    ):
        collector = MagicMock()
        collector.collect = MagicMock(return_value=fake_raw_evidence)

        def classifier(pkg):
            return classify_with_baseline(pkg, keyword_classify)

        result = await run_scenario(
            scenario_id="01-missing-env",
            namespace="demo",
            pod_name="demo-app-abc",
            collector=collector,
            preprocessor=FakePreprocessor(),
            redactor=FakeRedactor(),
            classifier=classifier,
            gt_path=gt_path,
        )
        assert isinstance(result, EvaluationResult)
        assert result.category_correct is True

    @pytest.mark.asyncio
    async def test_run_scenario_records_latency(self, fake_raw_evidence, fake_report, gt_path):
        collector = MagicMock()
        collector.collect = MagicMock(return_value=fake_raw_evidence)
        provider = MagicMock()
        provider.analyse = AsyncMock(return_value=fake_report)

        result = await run_scenario(
            scenario_id="01-missing-env",
            namespace="demo",
            pod_name="demo-app-abc",
            collector=collector,
            preprocessor=FakePreprocessor(),
            redactor=FakeRedactor(),
            classifier=lambda pkg: classify_with_llm(pkg, provider),
            gt_path=gt_path,
        )
        assert result.latency_s >= 0.0


class TestSaveResults:
    def test_save_results_writes_json(self, tmp_path: Path):
        results = [
            EvaluationResult(
                scenario_id="01",
                root_cause_correct=True,
                category_correct=True,
                schema_valid=True,
                latency_s=1.0,
                confidence=0.9,
                evidence_count=2,
                remediation_keywords_hit=3,
            )
        ]
        path = tmp_path / "results.json"
        save_results(results, path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["scenario_id"] == "01"

    def test_save_results_empty_list(self, tmp_path: Path):
        path = tmp_path / "empty.json"
        save_results([], path)
        assert json.loads(path.read_text()) == []


class TestEvaluationHarness:
    def test_can_be_instantiated(self):
        h = EvaluationHarness(
            collector=MagicMock(),
            preprocessor=FakePreprocessor(),
            redactor=FakeRedactor(),
        )
        assert h is not None

    @pytest.mark.asyncio
    async def test_run_all_returns_list(self, fake_raw_evidence, fake_report, tmp_path):
        collector = MagicMock()
        collector.collect = MagicMock(return_value=fake_raw_evidence)
        provider = MagicMock()
        provider.analyse = AsyncMock(return_value=fake_report)

        # Build ground truth files
        gt_dir = tmp_path / "gt"
        gt_dir.mkdir()
        gt = {
            "scenario_id": "01-missing-env",
            "true_root_cause": "Missing required environment variable DATABASE_URL",
            "true_affected_component": "demo-app",
            "true_failure_category": "config",
            "true_severity": "critical",
            "correct_remediation_keywords": ["DATABASE_URL", "environment variable"],
        }
        (gt_dir / "01-missing-env.json").write_text(json.dumps(gt))

        h = EvaluationHarness(
            collector=collector,
            preprocessor=FakePreprocessor(),
            redactor=FakeRedactor(),
            gt_dir=gt_dir,
        )

        results = await h.run_all(
            scenarios=["01-missing-env"],
            namespace="demo",
            pod_name="demo-app-abc",
            classifier=lambda pkg: classify_with_llm(pkg, provider),
        )
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0].scenario_id == "01-missing-env"
