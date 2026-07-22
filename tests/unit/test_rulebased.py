from k8s_llm_shared import EvidencePackage

from evaluation.baselines.rulebased import (
    RuleBasedClassifier,
    rule_classify,
)


def make_pkg(**kwargs):
    defaults = dict(
        namespace="demo",
        pod_name="demo-app-abc",
        current_logs="",
        previous_logs="",
        pod_status_summary="",
        k8s_events_filtered="",
        restart_count=0,
    )
    defaults.update(kwargs)
    return EvidencePackage(**defaults)


class TestRuleBasedClassifier:
    def test_can_be_instantiated(self):
        c = RuleBasedClassifier()
        assert c is not None

    def test_classify_returns_string(self):
        c = RuleBasedClassifier()
        result = c.classify(make_pkg())
        assert isinstance(result, str)

    def test_function_and_class_match(self):
        pkg = make_pkg(current_logs="OOMKilled", pod_status_summary="OOMKilled")
        assert rule_classify(pkg) == RuleBasedClassifier().classify(pkg)


class TestRuleBasedDetection:
    def test_detects_image_pull_failure_from_status(self):
        pkg = make_pkg(
            pod_status_summary="State: Waiting Reason: ImagePullBackOff",
            restart_count=0,
        )
        assert rule_classify(pkg) == "image"

    def test_detects_image_pull_failure_from_logs(self):
        pkg = make_pkg(current_logs="Failed to pull image: ErrImagePull")
        assert rule_classify(pkg) == "image"

    def test_detects_image_pull_from_events(self):
        pkg = make_pkg(
            k8s_events_filtered="Warning Failed: Error: ImagePullBackOff"
        )
        assert rule_classify(pkg) == "image"

    def test_detects_resource_oom_from_status(self):
        pkg = make_pkg(
            pod_status_summary="Last State: Terminated Reason: OOMKilled",
            restart_count=2,
        )
        assert rule_classify(pkg) == "resource"

    def test_detects_resource_oom_from_logs(self):
        pkg = make_pkg(
            current_logs="fatal error: out of memory",
            restart_count=1,
        )
        assert rule_classify(pkg) == "resource"

    def test_detects_resource_oom_from_events(self):
        pkg = make_pkg(
            k8s_events_filtered="Warning Killing: Container was killed due to OOMKilled",
            pod_status_summary="Last State: Terminated Reason: OOMKilled",
        )
        assert rule_classify(pkg) == "resource"

    def test_detects_config_missing_env(self):
        pkg = make_pkg(
            current_logs="FATAL: Missing required configuration DATABASE_URL",
            previous_logs="RuntimeError: environment variable not set",
            restart_count=3,
        )
        assert rule_classify(pkg) == "config"

    def test_detects_config_keyerror(self):
        pkg = make_pkg(
            current_logs="KeyError: 'DATABASE_URL'",
            restart_count=2,
        )
        assert rule_classify(pkg) == "config"

    def test_detects_dependency_connection_refused(self):
        pkg = make_pkg(
            current_logs="ERROR connection refused to database host:5432",
            restart_count=2,
        )
        assert rule_classify(pkg) == "dependency"

    def test_detects_dependency_timeout(self):
        pkg = make_pkg(
            current_logs="timeout while connecting to upstream service",
            restart_count=1,
        )
        assert rule_classify(pkg) == "dependency"

    def test_detects_dependency_over_probe(self):
        """When connection refused co-occurs with readiness probe failure,
        dependency should win (probe failure is a symptom)."""
        pkg = make_pkg(
            current_logs="Database connection failed: connection refused",
            k8s_events_filtered="Warning Unhealthy: Readiness probe failed",
        )
        assert rule_classify(pkg) == "dependency"

    def test_detects_probe_failure_from_events(self):
        pkg = make_pkg(
            k8s_events_filtered="Warning Unhealthy: Readiness probe failed: "
            "HTTP probe failed with statuscode: 404",
            pod_status_summary="Ready: False",
        )
        assert rule_classify(pkg) == "probe"

    def test_detects_probe_failure_liveness(self):
        pkg = make_pkg(
            k8s_events_filtered="Warning Unhealthy: Liveness probe failed: "
            "HTTP probe failed with statuscode: 504\n"
            "Warning Killing: Container failed liveness probe",
            pod_status_summary="Last State: Terminated Reason: Error",
            restart_count=4,
        )
        assert rule_classify(pkg) == "probe"

    def test_detects_probe_from_ready_false_no_restarts(self):
        """Ready=False with no restarts and no other root cause → probe."""
        pkg = make_pkg(
            pod_status_summary="State: Running Ready: False Restart Count: 0",
        )
        assert rule_classify(pkg) == "probe"

    def test_detects_network_port_in_use(self):
        pkg = make_pkg(
            current_logs="Error: address already in use port 8080",
            restart_count=0,
        )
        assert rule_classify(pkg) == "network"

    def test_detects_crash_from_exception_and_restarts(self):
        pkg = make_pkg(
            current_logs="Traceback (most recent call last): RuntimeError",
            previous_logs="ZeroDivisionError: division by zero",
            restart_count=5,
        )
        assert rule_classify(pkg) == "crash"

    def test_detects_crash_from_container_cannot_run(self):
        """Container with nonexistent binary → ContainerCannotRun → crash."""
        pkg = make_pkg(
            pod_status_summary=(
                "Last State: Terminated\n"
                "  Reason: ContainerCannotRun\n"
                "  Message: executable file not found in $PATH: /bin/nonexistent"
            ),
            restart_count=8,
        )
        assert rule_classify(pkg) == "crash"

    def test_detects_crash_from_start_error(self):
        pkg = make_pkg(
            pod_status_summary="Last State: Terminated Reason: StartError",
            restart_count=5,
        )
        assert rule_classify(pkg) == "crash"

    def test_detects_crash_from_startup_fault(self):
        pkg = make_pkg(
            previous_logs="FATAL: STARTUP_FAULT=crash -- raising exception",
            pod_status_summary="Reason: CrashLoopBackOff",
            restart_count=6,
        )
        assert rule_classify(pkg) == "crash"

    def test_returns_unknown_when_no_signals(self):
        pkg = make_pkg(current_logs="INFO: server started successfully")
        assert rule_classify(pkg) == "unknown"

    def test_returns_unknown_for_empty_evidence(self):
        assert rule_classify(make_pkg()) == "unknown"


class TestRuleBasedPriority:
    """Rules are evaluated in priority order; first match wins."""

    def test_image_takes_priority_over_resource(self):
        pkg = make_pkg(
            pod_status_summary="ImagePullBackOff OOMKilled memory",
            restart_count=2,
        )
        assert rule_classify(pkg) == "image"

    def test_resource_takes_priority_over_config(self):
        pkg = make_pkg(
            pod_status_summary="OOMKilled",
            current_logs="Missing environment variable DATABASE_URL",
            restart_count=1,
        )
        assert rule_classify(pkg) == "resource"

    def test_config_takes_priority_over_dependency(self):
        pkg = make_pkg(
            current_logs="Missing environment variable DATABASE_URL connection refused",
            restart_count=1,
        )
        assert rule_classify(pkg) == "config"

    def test_dependency_takes_priority_over_probe(self):
        pkg = make_pkg(
            current_logs="connection refused to database",
            k8s_events_filtered="Warning Unhealthy: Readiness probe failed",
        )
        assert rule_classify(pkg) == "dependency"

    def test_probe_takes_priority_over_crash(self):
        """Liveness probe failure with restarts → probe (not crash)."""
        pkg = make_pkg(
            k8s_events_filtered="Warning Unhealthy: Liveness probe failed",
            pod_status_summary="Reason: CrashLoopBackOff",
            restart_count=4,
        )
        assert rule_classify(pkg) == "probe"

    def test_crash_takes_priority_over_network(self):
        pkg = make_pkg(
            current_logs="Traceback RuntimeError",
            pod_status_summary="Reason: CrashLoopBackOff",
            restart_count=5,
        )
        assert rule_classify(pkg) == "crash"


class TestRuleBasedDetailedAndExplanation:
    def test_classify_detailed_returns_dict(self):
        c = RuleBasedClassifier()
        result = c.classify_detailed(make_pkg(current_logs="OOMKilled"))
        assert isinstance(result, dict)
        assert result["failure_category"] == "resource"
        assert "confidence" in result
        assert "matched_rule" in result

    def test_classify_detailed_unknown(self):
        c = RuleBasedClassifier()
        result = c.classify_detailed(make_pkg())
        assert result["failure_category"] == "unknown"
        assert result["confidence"] == 0.0

    def test_explain_returns_dict(self):
        c = RuleBasedClassifier()
        explanation = c.explain(make_pkg(current_logs="OOMKilled"))
        assert isinstance(explanation, dict)
        assert "matched_rule" in explanation
        assert "evidence_signals" in explanation

    def test_explain_records_matched_rule(self):
        c = RuleBasedClassifier()
        pkg = make_pkg(pod_status_summary="ImagePullBackOff")
        explanation = c.explain(pkg)
        assert explanation["matched_rule"] == "image"

    def test_explain_records_unknown_when_no_match(self):
        c = RuleBasedClassifier()
        explanation = c.explain(make_pkg())
        assert explanation["matched_rule"] == "unknown"

    def test_explain_includes_last_state_reason(self):
        c = RuleBasedClassifier()
        pkg = make_pkg(
            pod_status_summary="Last State: Terminated Reason: OOMKilled"
        )
        explanation = c.explain(pkg)
        assert "last_state_reason" in explanation
        assert explanation["last_state_reason"] == "oomkilled"
