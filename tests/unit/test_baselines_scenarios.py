"""End-to-end baseline classification tests for all 10 fault scenarios.

Tests both keyword and rule-based baselines against realistic evidence
fixtures that simulate what the preprocessor would output from a real
k8s cluster for each fault scenario.

Scenarios 08 (bad-configmap) and 10 (wrong-port) are "subtle" scenarios
where the pod runs fine and no error signals appear in pod evidence alone.
These are documented limitations of the baselines — the collector would
need configmap/service inspection to detect them.
"""
import pytest

from evaluation.baselines.keyword import KeywordClassifier, keyword_classify
from evaluation.baselines.rulebased import RuleBasedClassifier, rule_classify
from evaluation.harness import classify_with_baseline
from tests.fixtures.scenario_evidence import (
    SCENARIO_IDS,
    TRUE_CATEGORIES,
    all_fixtures,
)

# Scenarios that baselines CAN detect from pod evidence alone.
# Scenario 08 is detectable because kubectl describe pod shows ConfigMap
# env vars (LOG_LEVEL=INVALID) in the pod status output.
DETECTABLE = {
    "01-missing-env",
    "02-db-unavailable",
    "03-crashloop",
    "04-imagepull",
    "05-oom",
    "06-readiness",
    "07-liveness",
    "08-bad-configmap",
    "09-app-exception",
}

# Scenarios that baselines CANNOT detect from pod evidence alone.
# Scenario 10 (wrong-port) requires Service/endpoint inspection — the pod
# runs fine and no error signals appear in pod logs, status, or events.
UNDETECTABLE = {
    "10-wrong-port",
}


@pytest.fixture(scope="module")
def fixtures():
    return all_fixtures()


# ─── Keyword Baseline ──────────────────────────────────────────────


class TestKeywordBaselineScenarios:
    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_keyword_classifies_correctly(self, fixtures, scenario_id):
        """Keyword baseline should classify all detectable scenarios correctly."""
        pkg = fixtures[scenario_id]
        result = keyword_classify(pkg)
        expected = TRUE_CATEGORIES[scenario_id]
        assert result == expected, (
            f"Scenario {scenario_id}: expected '{expected}', got '{result}'"
        )

    @pytest.mark.parametrize("scenario_id", sorted(UNDETECTABLE))
    def test_keyword_returns_unknown_for_subtle(self, fixtures, scenario_id):
        """Keyword baseline returns 'unknown' for subtle scenarios without
        error signals in pod evidence. This is a documented limitation."""
        pkg = fixtures[scenario_id]
        result = keyword_classify(pkg)
        assert result == "unknown", (
            f"Scenario {scenario_id}: expected 'unknown', got '{result}'"
        )


class TestKeywordBaselineDetailed:
    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_detailed_has_nonzero_confidence(self, fixtures, scenario_id):
        pkg = fixtures[scenario_id]
        c = KeywordClassifier()
        detail = c.classify_detailed(pkg)
        assert detail["confidence"] > 0, f"Scenario {scenario_id}: zero confidence"
        assert detail["failure_category"] == TRUE_CATEGORIES[scenario_id]

    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_detailed_has_matched_keywords(self, fixtures, scenario_id):
        pkg = fixtures[scenario_id]
        c = KeywordClassifier()
        detail = c.classify_detailed(pkg)
        assert len(detail["matched_keywords"]) > 0, (
            f"Scenario {scenario_id}: no matched keywords"
        )


# ─── Rule-Based Baseline ──────────────────────────────────────────


class TestRuleBasedBaselineScenarios:
    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_rulebased_classifies_correctly(self, fixtures, scenario_id):
        """Rule-based baseline should classify all detectable scenarios correctly."""
        pkg = fixtures[scenario_id]
        result = rule_classify(pkg)
        expected = TRUE_CATEGORIES[scenario_id]
        assert result == expected, (
            f"Scenario {scenario_id}: expected '{expected}', got '{result}'"
        )

    @pytest.mark.parametrize("scenario_id", sorted(UNDETECTABLE))
    def test_rulebased_returns_unknown_for_subtle(self, fixtures, scenario_id):
        """Rule-based baseline returns 'unknown' for subtle scenarios."""
        pkg = fixtures[scenario_id]
        result = rule_classify(pkg)
        assert result == "unknown", (
            f"Scenario {scenario_id}: expected 'unknown', got '{result}'"
        )


class TestRuleBasedBaselineDetailed:
    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_detailed_has_nonzero_confidence(self, fixtures, scenario_id):
        pkg = fixtures[scenario_id]
        c = RuleBasedClassifier()
        detail = c.classify_detailed(pkg)
        assert detail["confidence"] > 0, f"Scenario {scenario_id}: zero confidence"
        assert detail["failure_category"] == TRUE_CATEGORIES[scenario_id]

    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_detailed_has_matched_rule(self, fixtures, scenario_id):
        pkg = fixtures[scenario_id]
        c = RuleBasedClassifier()
        detail = c.classify_detailed(pkg)
        assert detail["matched_rule"] != "unknown", (
            f"Scenario {scenario_id}: no matched rule"
        )


# ─── Harness classify_with_baseline Integration ────────────────────


class TestHarnessBaselineIntegration:
    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_keyword_harness_produces_report(self, fixtures, scenario_id):
        """classify_with_baseline with KeywordClassifier produces a report dict
        with the correct category and specific root cause."""
        pkg = fixtures[scenario_id]
        kw = KeywordClassifier()
        report = classify_with_baseline(pkg, kw)
        assert report["failure_category"] == TRUE_CATEGORIES[scenario_id]
        assert "likely_root_cause" in report
        assert "confidence" in report
        assert "suggested_fix" in report
        assert "recommended_commands" in report
        assert report["likely_root_cause"] != "Baseline classified this as unknown."

    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_rulebased_harness_produces_report(self, fixtures, scenario_id):
        """classify_with_baseline with RuleBasedClassifier produces a report dict
        with the correct category and specific root cause."""
        pkg = fixtures[scenario_id]
        rb = RuleBasedClassifier()
        report = classify_with_baseline(pkg, rb)
        assert report["failure_category"] == TRUE_CATEGORIES[scenario_id]
        assert "likely_root_cause" in report
        assert "confidence" in report
        assert "suggested_fix" in report
        assert "recommended_commands" in report

    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_keyword_harness_confidence_above_zero(self, fixtures, scenario_id):
        """The improved keyword baseline should have non-zero confidence."""
        pkg = fixtures[scenario_id]
        kw = KeywordClassifier()
        report = classify_with_baseline(pkg, kw)
        assert report["confidence"] > 0, f"Scenario {scenario_id}: zero confidence"

    @pytest.mark.parametrize("scenario_id", sorted(DETECTABLE))
    def test_rulebased_harness_confidence_above_zero(self, fixtures, scenario_id):
        """The improved rule-based baseline should have non-zero confidence."""
        pkg = fixtures[scenario_id]
        rb = RuleBasedClassifier()
        report = classify_with_baseline(pkg, rb)
        assert report["confidence"] > 0, f"Scenario {scenario_id}: zero confidence"


# ─── Summary Test ─────────────────────────────────────────────────


class TestBaselineSummary:
    def test_keyword_accuracy_on_detectable(self, fixtures):
        """Keyword baseline accuracy should be 100% on detectable scenarios."""
        correct = sum(
            1
            for sid in sorted(DETECTABLE)
            if keyword_classify(fixtures[sid]) == TRUE_CATEGORIES[sid]
        )
        total = len(DETECTABLE)
        accuracy = correct / total
        assert accuracy == 1.0, (
            f"Keyword baseline accuracy: {correct}/{total} = {accuracy:.0%}. "
            f"Expected 100% on detectable scenarios."
        )

    def test_rulebased_accuracy_on_detectable(self, fixtures):
        """Rule-based baseline accuracy should be 100% on detectable scenarios."""
        correct = sum(
            1
            for sid in sorted(DETECTABLE)
            if rule_classify(fixtures[sid]) == TRUE_CATEGORIES[sid]
        )
        total = len(DETECTABLE)
        accuracy = correct / total
        assert accuracy == 1.0, (
            f"Rule-based baseline accuracy: {correct}/{total} = {accuracy:.0%}. "
            f"Expected 100% on detectable scenarios."
        )

    def test_both_baselines_agree_on_detectable(self, fixtures):
        """Both baselines should produce the same (correct) result on
        all detectable scenarios."""
        for sid in sorted(DETECTABLE):
            kw_result = keyword_classify(fixtures[sid])
            rb_result = rule_classify(fixtures[sid])
            expected = TRUE_CATEGORIES[sid]
            assert kw_result == rb_result == expected, (
                f"Scenario {sid}: keyword={kw_result}, "
                f"rulebased={rb_result}, expected={expected}"
            )

    def test_all_10_scenarios_covered(self):
        """Verify that DETECTABLE + UNDETECTABLE = all 10 scenarios."""
        assert DETECTABLE | UNDETECTABLE == set(SCENARIO_IDS)
        assert len(DETECTABLE) + len(UNDETECTABLE) == 10
        assert DETECTABLE & UNDETECTABLE == set()
