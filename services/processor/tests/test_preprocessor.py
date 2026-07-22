from app.preprocessor import LogPreprocessor
from k8s_llm_shared import EvidencePackage, RawEvidence


class TestLogPreprocessor:
    def setup_method(self):
        self.pre = LogPreprocessor()

    def test_filter_with_context_removes_noise_far_from_signal(self):
        logs = """2025-01-01T00:00:00Z INFO GET /health
2025-01-01T00:00:01Z INFO GET /ready
2025-01-01T00:00:10Z INFO GET /metrics
2025-01-01T00:00:02Z ERROR Database connection refused
2025-01-01T00:00:03Z INFO GET /metrics"""
        pre = LogPreprocessor(context_window=0)
        result = pre._filter_with_context(logs)
        assert "Database connection refused" in result
        assert "GET /health" not in result
        assert "GET /ready" not in result
        assert "GET /metrics" not in result

    def test_filter_with_context_keeps_signal_with_context_window(self):
        logs = """line 1 ok
line 2 normal
ERROR something broke
line 4 after
line 5 more"""
        pre = LogPreprocessor(context_window=1)
        result = pre._filter_with_context(logs)
        assert "line 2 normal" in result
        assert "ERROR something broke" in result
        assert "line 4 after" in result

    def test_filter_with_context_deduplicates_duplicate_lines(self):
        logs = """ERROR first failure
INFO normal
ERROR first failure
INFO normal
ERROR second failure"""
        result = self.pre._filter_with_context(logs)
        assert result.count("ERROR first failure") == 1

    def test_filter_with_context_limits_max_lines(self):
        pre = LogPreprocessor(max_log_lines=2, context_window=0)
        logs = "\n".join([f"ERROR line {i}" for i in range(20)])
        result = pre._filter_with_context(logs)
        assert len(result.splitlines()) <= 2

    def test_filter_with_context_handles_empty_input(self):
        result = self.pre._filter_with_context("")
        assert result == ""

    def test_is_noise_detects_health_probes(self):
        """
        Case-sensitive matching:
        - regular health/ready/metrics paths match
        - empty line matches
        """
        assert self.pre._is_noise("GET /health 200")
        assert self.pre._is_noise("GET /ready 200 OK")
        assert self.pre._is_noise("GET /metrics prometheus_data")
        assert self.pre._is_noise("")

    def test_is_noise_rejects_non_noise(self):
        assert not self.pre._is_noise("ERROR DB connection failed")

    def test_is_signal_detects_error_keywords(self):
        assert self.pre._is_signal("ERROR connection refused")
        assert self.pre._is_signal("FATAL: Out of memory")
        assert self.pre._is_signal("Traceback (most recent call last):")
        assert self.pre._is_signal("CrashLoopBackOff detected")
        assert self.pre._is_signal("missing required config")

    def test_is_signal_rejects_normal_lines(self):
        assert not self.pre._is_signal("GET /health 200")
        assert not self.pre._is_signal("INFO Server started")

    def test_extract_events_filters_warnings(self):
        events = """10s Normal Scheduled pod/demo-app Node assigned
10s Warning BackOff pod/demo-app Back-off restarting
20s Normal Pulled pod/demo-app Container image pulled"""
        result = self.pre._extract_events(events)
        assert "Warning BackOff" in result
        assert "Normal Scheduled" not in result

    def test_process_returns_evidence_package(self):
        raw = RawEvidence(
            namespace="demo",
            pod_name="demo-app-abc",
            current_logs="ERROR connection refused",
            previous_logs="WARN previous startup failed",
            pod_status="Status: CrashLoopBackOff\n" * 500,
            k8s_events="10s Warning BackOff pod/demo-app restarting",
            restart_count=3,
        )
        pkg = self.pre.process(raw)
        assert isinstance(pkg, EvidencePackage)
        assert pkg.namespace == "demo"
        assert pkg.pod_name == "demo-app-abc"
        assert "connection refused" in pkg.current_logs
        assert pkg.restart_count == 3
        assert isinstance(pkg.pod_status_summary, str)

    def test_process_truncates_long_pod_status(self):
        raw = RawEvidence(
            namespace="demo", pod_name="p",
            pod_status="Line\n" * 5000,
        )
        pkg = self.pre.process(raw)
        assert len(pkg.pod_status_summary) <= 2000

    def test_evidence_package_defaults(self):
        pkg = EvidencePackage(
            namespace="ns", pod_name="p",
            current_logs="", previous_logs="",
            pod_status_summary="", k8s_events_filtered="",
            restart_count=0,
        )
        assert pkg.restart_count == 0

    def test_identity_works_for_complex_realistic_logs(self):
        logs = """2025-06-01 10:00:00 INFO Server started on port 8000
2025-06-01 10:00:01 INFO Loading configuration
2025-06-01 10:00:02 ERROR [MainThread] RuntimeError: Missing config: DATABASE_URL
2025-06-01 10:00:02 ERROR [MainThread] Traceback (most recent call last):
2025-06-01 10:00:02 ERROR [MainThread]   File "app/main.py", line 12, in lifespan
2025-06-01 10:00:02 ERROR [MainThread]     raise RuntimeError("Missing config: DATABASE_URL")
2025-06-01 10:00:03 INFO Shutting down"""
        pre = LogPreprocessor(context_window=1)
        result = pre._filter_with_context(logs)
        assert "RuntimeError" in result
        assert "Traceback" in result
        assert "DATABASE_URL" in result
        assert "Loading configuration" in result
        assert "Shutting down" in result

    def test_context_window_zero_only_signal(self):
        logs = """INFO before
INFO before2
ERROR crash
INFO after
INFO after2"""
        pre = LogPreprocessor(context_window=0)
        result = pre._filter_with_context(logs)
        assert "ERROR crash" in result
        assert "INFO before" not in result
        assert "INFO after" not in result

    def test_context_window_at_start_no_preceding(self):
        logs = """ERROR first crash
INFO line 2
INFO line 3"""
        pre = LogPreprocessor(context_window=2)
        result = pre._filter_with_context(logs)
        assert "ERROR first crash" in result
        assert "INFO line 2" in result
        assert "INFO line 3" in result

    def test_context_window_at_end_no_following(self):
        logs = """INFO line 1
INFO line 2
ERROR last crash"""
        pre = LogPreprocessor(context_window=2)
        result = pre._filter_with_context(logs)
        assert "ERROR last crash" in result
        assert "INFO line 1" in result
        assert "INFO line 2" in result

    def test_signal_line_also_noise_is_excluded(self):
        logs = """ERROR GET /health failed
INFO normal line"""
        result = self.pre._filter_with_context(logs)
        assert "GET /health" not in result
        assert "INFO normal line" not in result  # no signal to keep context

    def test_only_noise_lines_yields_empty(self):
        logs = """GET /health 200
GET /ready 200
GET /metrics 100"""
        result = self.pre._filter_with_context(logs)
        assert result == ""

    def test_mixed_noise_and_signal_excludes_noise_within_window(self):
        logs = """INFO setup
GET /health 200
ERROR database crash
GET /metrics 100
INFO teardown"""
        pre = LogPreprocessor(context_window=1)
        result = pre._filter_with_context(logs)
        assert "ERROR database crash" in result
        # Context lines include the noise lines (but not filtered)
        assert "GET /health 200" in result  # noise line at context boundary
        assert "GET /metrics 100" in result
        # INFO setup is outside context window
        assert "INFO setup" not in result

    def test_whitespace_only_lines_are_noise(self):
        logs = """ERROR something broke


INFO after space"""
        pre = LogPreprocessor(context_window=1)
        result = pre._filter_with_context(logs)
        assert "ERROR something broke" in result
        # Whitespace-only lines are stripped and deduplicated
        # INFO after space is farther than context_window from signal
        # (signal at line 0, context_window=1 covers lines 0-1)
        assert "INFO after space" not in result

    def test_all_signal_patterns(self):
        for keyword in [
            "error", "exception", "traceback", "fatal", "critical",
            "failed", "refused", "timeout",
        ]:
            assert self.pre._is_signal(f"something {keyword} happened"), f"missing {keyword}"
        for keyword in [
            "OOMKilled", "CrashLoopBackOff", "ImagePullBackOff", "BackOff", "Unhealthy",
        ]:
            assert self.pre._is_signal(f"Pod {keyword}"), f"missing {keyword}"
        for keyword in [
            "missing", "not found", "permission denied", "address already in use",
        ]:
            assert self.pre._is_signal(f"Error: {keyword}"), f"missing {keyword}"

    def test_is_noise_is_case_sensitive(self):
        assert not self.pre._is_noise("GET /Health 200")
        assert not self.pre._is_noise("GET /Ready 200")

    def test_extract_events_empty_input(self):
        assert self.pre._extract_events("") == ""

    def test_extract_events_no_warnings(self):
        events = "10s Normal Scheduled pod\n20s Normal Pulled image"
        result = self.pre._extract_events(events)
        assert result == ""

    def test_extract_events_signal_without_warning(self):
        events = "10s Normal BackOff pod restarting"
        result = self.pre._extract_events(events)
        assert "BackOff" in result

    def test_extract_events_mixed_signals_and_warnings(self):
        events = """10s Normal Scheduled pod
10s Warning BackOff restarted
20s Error CrashLoopBackOff detected
30s Normal Pulled image"""
        result = self.pre._extract_events(events)
        assert "Warning BackOff" in result
        assert "CrashLoopBackOff" in result
        assert "Normal Scheduled" not in result
        assert "Normal Pulled" not in result

    def test_process_preserves_container_states_not_in_output(self):
        raw = RawEvidence(
            namespace="demo", pod_name="p", current_logs="ERROR boom",
            container_states=[{"name": "app", "state": {"waiting": {}}}],
        )
        pkg = self.pre.process(raw)
        assert pkg.restart_count == 0

    def test_constructor_custom_values(self):
        pre = LogPreprocessor(max_log_lines=50, context_window=5)
        assert pre.max_log_lines == 50
        assert pre.context_window == 5

    def test_max_log_lines_respected_even_with_context(self):
        pre = LogPreprocessor(max_log_lines=3, context_window=2)
        logs = "\n".join([f"ERROR line {i}" for i in range(100)])
        result = pre._filter_with_context(logs)
        assert len(result.splitlines()) <= 3
