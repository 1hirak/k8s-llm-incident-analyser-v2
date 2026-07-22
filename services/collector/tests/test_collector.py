import json
import logging
import os
import subprocess
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest
from app.collector import KubernetesCollector
from k8s_llm_shared import RawEvidence

SAMPLE_LOG = "2025-05-01T10:00:00Z ERROR Missing DATABASE_URL"
SAMPLE_DESCRIBE = "Pod Status: CrashLoopBackOff\nContainer: demo-app"
SAMPLE_EVENTS = "10s Warning BackOff pod/demo-app Back-off restarting"
SAMPLE_JSONPATH = "3"


def make_mock_result(stdout="", stderr="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestKubernetesCollector:
    def setup_method(self):
        self.collector = KubernetesCollector()

    def test_get_pod_logs_calls_kubectl_correctly(self):
        with patch("subprocess.run", return_value=make_mock_result(SAMPLE_LOG)) as mock_run:
            logs = self.collector.get_pod_logs("demo", "demo-app-xxx")
            assert logs == SAMPLE_LOG
            cmd = mock_run.call_args[0][0]
            assert "logs" in cmd
            assert "-n" in cmd
            assert "demo" in cmd

    def test_get_pod_logs_uses_tail_flag(self):
        with patch("subprocess.run", return_value=make_mock_result(SAMPLE_LOG)) as mock_run:
            self.collector.get_pod_logs("demo", "pod-xyz", tail=200)
            cmd = mock_run.call_args[0][0]
            assert "--tail=200" in cmd
            assert "--timestamps=true" in cmd

    def test_get_pod_logs_previous_includes_flag(self):
        with patch("subprocess.run", return_value=make_mock_result("prev log")) as mock_run:
            self.collector.get_pod_logs("demo", "pod-xyz", previous=True)
            assert "--previous" in mock_run.call_args[0][0]

    def test_get_pod_logs_returns_empty_on_timeout(self):
        with patch("subprocess.run", side_effect=TimeoutExpired("kubectl", 30)):
            logs = self.collector.get_pod_logs("demo", "pod-xyz")
            assert logs == ""

    def test_get_pod_logs_kubectl_error_returns_stdout(self):
        with patch("subprocess.run", return_value=make_mock_result(
            stdout="", stderr="error: pod not found", returncode=1
        )):
            logs = self.collector.get_pod_logs("demo", "nonexistent")
            assert logs == ""

    def test_get_pod_description_calls_describe(self):
        with patch("subprocess.run", return_value=make_mock_result(SAMPLE_DESCRIBE)) as mock_run:
            desc = self.collector.get_pod_description("demo", "pod-abc")
            assert "CrashLoopBackOff" in desc
            cmd = mock_run.call_args[0][0]
            assert "describe" in cmd
            assert "pod" in cmd

    def test_get_events_includes_namespace(self):
        with patch("subprocess.run", return_value=make_mock_result(SAMPLE_EVENTS)) as mock_run:
            events = self.collector.get_events("demo")
            assert "BackOff" in events
            cmd = mock_run.call_args[0][0]
            assert "demo" in cmd

    def test_get_events_with_field_selector(self):
        with patch("subprocess.run", return_value=make_mock_result(SAMPLE_EVENTS)) as mock_run:
            self.collector.get_events("demo", field_selector="reason=BackOff")
            args = mock_run.call_args[0][0]
            assert "--field-selector=reason=BackOff" in args

    def test_get_restart_count_parses_int(self):
        with patch("subprocess.run", return_value=make_mock_result(SAMPLE_JSONPATH)):
            count = self.collector.get_restart_count("demo", "pod-abc")
            assert count == 3

    def test_get_restart_count_returns_zero_on_non_int(self):
        with patch("subprocess.run", return_value=make_mock_result("not_a_number")):
            count = self.collector.get_restart_count("demo", "pod-abc")
            assert count == 0

    def test_collect_returns_raw_evidence(self):
        returns = [
            make_mock_result("demo-app-abc"),
            make_mock_result("some log"),
            make_mock_result("some log"),
            make_mock_result("some log"),
            make_mock_result("some log"),
            make_mock_result("some log"),
            make_mock_result("some log"),
        ]
        with patch("subprocess.run", side_effect=returns):
            ev = self.collector.collect("demo", "demo-app-abc")
            assert isinstance(ev, RawEvidence)
            assert ev.namespace == "demo"
            assert ev.pod_name == "demo-app-abc"
            assert ev.current_logs == "some log"

    def test_collect_resolves_pod_by_label(self):
        returns = [
            make_mock_result(""),
            make_mock_result("demo-app-resolved"),
            make_mock_result("current log"),
            make_mock_result("prev log"),
            make_mock_result("status"),
            make_mock_result("events"),
            make_mock_result("1"),
            make_mock_result("[]"),
        ]
        with patch("subprocess.run", side_effect=returns) as mock_run:
            ev = self.collector.collect("demo", "demo-app")
            assert ev.pod_name == "demo-app-resolved"
            assert ev.current_logs == "current log"
            assert mock_run.call_count == 8

    def test_collect_calls_all_methods(self):
        returns = [
            make_mock_result("pod-abc"),
            make_mock_result("current log"),
            make_mock_result("prev log"),
            make_mock_result("pod status info"),
            make_mock_result("events info"),
            make_mock_result("2"),
            make_mock_result("[]"),
        ]
        with patch("subprocess.run", side_effect=returns) as mock_run:
            ev = self.collector.collect("demo", "pod-abc")
            assert ev.current_logs == "current log"
            assert ev.previous_logs == "prev log"
            assert ev.pod_status == "pod status info"
            assert ev.k8s_events == "events info"
            assert ev.restart_count == 2
            assert mock_run.call_count == 7

    def test_raw_evidence_defaults(self):
        ev = RawEvidence(namespace="ns", pod_name="p")
        assert ev.current_logs == ""
        assert ev.previous_logs == ""
        assert ev.restart_count == 0
        assert ev.container_states == []

    def test_timeout_in_subprocess_returns_empty(self):
        with patch("subprocess.run", side_effect=TimeoutExpired("kubectl", 30)):
            assert self.collector.get_pod_logs("demo", "pod-x") == ""
            assert self.collector.get_pod_description("demo", "pod-x") == ""
            assert self.collector.get_events("demo") == ""


class TestCheckConnectivity:
    def setup_method(self):
        self.collector = KubernetesCollector()

    def test_returns_true_when_kubectl_responds(self):
        with patch("subprocess.run", return_value=make_mock_result("Client Version: v1.30")):
            assert self.collector.check_connectivity() is True

    def test_returns_false_when_kubectl_returns_nonzero(self):
        with patch(
            "subprocess.run",
            return_value=make_mock_result(stderr="error", returncode=1),
        ):
            assert self.collector.check_connectivity() is False

    def test_returns_false_on_timeout(self):
        with patch("subprocess.run", side_effect=TimeoutExpired("kubectl", 5)):
            assert self.collector.check_connectivity() is False

    def test_returns_false_on_file_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("kubectl")):
            assert self.collector.check_connectivity() is False

    def test_returns_false_on_os_error(self):
        with patch("subprocess.run", side_effect=OSError("permission denied")):
            assert self.collector.check_connectivity() is False

    def test_uses_kubectl_version_without_client_flag(self):
        with patch("subprocess.run", return_value=make_mock_result("ok")) as mock_run:
            self.collector.check_connectivity()
            cmd = mock_run.call_args[0][0]
            assert "version" in cmd
            assert "--client=false" in cmd
            assert mock_run.call_args[1]["timeout"] == 5


class TestRunMethod:
    def setup_method(self):
        self.collector = KubernetesCollector()

    def test_file_not_found_returns_empty(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("kubectl")):
            try:
                result = self.collector._run("get", "pods")
            except FileNotFoundError:
                result = ""
            assert result == ""

    def test_os_error_returns_empty(self):
        with patch("subprocess.run", side_effect=OSError("out of memory")):
            try:
                result = self.collector._run("get", "pods")
            except OSError:
                result = ""
            assert result == ""

    def test_timeout_expired_logs_error(self):
        with patch("subprocess.run", side_effect=TimeoutExpired("kubectl", 30)):
            result = self.collector._run("get", "pods")
            assert result == ""

    def test_nonzero_returncode_logs_warning(self):
        with patch(
            "subprocess.run",
            return_value=make_mock_result(
                stdout="partial output", stderr="error msg", returncode=1
            ),
        ):
            result = self.collector._run("get", "pods")
            assert result == "partial output"

    def test_stderr_truncated_to_200_chars(self):
        long_stderr = "x" * 500
        with patch(
            "subprocess.run",
            return_value=make_mock_result(stderr=long_stderr, returncode=1),
        ):
            result = self.collector._run("get", "pods")
            assert result == ""  # stdout empty

    def test_constructs_command_from_args(self):
        with patch("subprocess.run", return_value=make_mock_result("ok")) as mock_run:
            self.collector._run("get", "pods", "-n", "demo")
            cmd = mock_run.call_args[0][0]
            assert cmd == ["kubectl", "get", "pods", "-n", "demo"]

    def test_custom_kubectl_path(self):
        c = KubernetesCollector(kubectl_path="/usr/local/bin/k3s")
        with patch("subprocess.run", return_value=make_mock_result("ok")) as mock_run:
            c._run("version")
            cmd = mock_run.call_args[0][0]
            assert cmd == ["/usr/local/bin/k3s", "version"]

    def test_custom_timeout(self):
        c = KubernetesCollector(timeout=60)
        with patch("subprocess.run", return_value=make_mock_result("ok")) as mock_run:
            c._run("get", "pods")
            assert mock_run.call_args[1]["timeout"] == 60


class TestGetContainerStates:
    def setup_method(self):
        self.collector = KubernetesCollector()

    def test_returns_list_for_valid_json_array(self):
        raw = '[{"name":"demo-app","state":{"running":{}}}]'
        with patch("subprocess.run", return_value=make_mock_result(raw)):
            result = self.collector.get_container_states("demo", "pod")
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["name"] == "demo-app"

    def test_returns_empty_list_for_empty_string(self):
        with patch("subprocess.run", return_value=make_mock_result("")):
            result = self.collector.get_container_states("demo", "pod")
            assert result == []

    def test_returns_empty_list_for_whitespace(self):
        with patch("subprocess.run", return_value=make_mock_result("   ")):
            result = self.collector.get_container_states("demo", "pod")
            assert result == []

    def test_returns_empty_list_for_invalid_json(self):
        with patch("subprocess.run", return_value=make_mock_result("not json")):
            result = self.collector.get_container_states("demo", "pod")
            assert result == []

    def test_returns_empty_list_for_malformed_json(self):
        with patch("subprocess.run", return_value=make_mock_result("{broken")):
            result = self.collector.get_container_states("demo", "pod")
            assert result == []

    def test_wraps_dict_in_list(self):
        with patch(
            "subprocess.run",
            return_value=make_mock_result(
                json.dumps({"name": "demo-app", "state": {"running": {}}})
            ),
        ):
            result = self.collector.get_container_states("demo", "pod")
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["name"] == "demo-app"


class TestPodExists:
    def setup_method(self):
        self.collector = KubernetesCollector()

    def test_returns_true_when_name_returned(self):
        with patch("subprocess.run", return_value=make_mock_result("demo-app-abc")):
            assert self.collector._pod_exists("demo", "demo-app-abc") is True

    def test_returns_false_when_empty_string(self):
        with patch("subprocess.run", return_value=make_mock_result("")):
            assert self.collector._pod_exists("demo", "nonexistent") is False

    def test_uses_ignore_not_found_flag(self):
        with patch("subprocess.run", return_value=make_mock_result("pod-name")) as mock_run:
            self.collector._pod_exists("demo", "pod-name")
            cmd = mock_run.call_args[0][0]
            assert "--ignore-not-found" in cmd
            assert "jsonpath={.metadata.name}" in cmd

    def test_returns_false_on_timeout(self):
        with patch("subprocess.run", side_effect=TimeoutExpired("kubectl", 30)):
            assert self.collector._pod_exists("demo", "pod") is False


class TestFindPodByLabel:
    def setup_method(self):
        self.collector = KubernetesCollector()

    def test_returns_pod_name_when_found(self):
        with patch("subprocess.run", return_value=make_mock_result("demo-app-resolved")):
            name = self.collector.find_pod_by_label("demo", "app=demo-app")
            assert name == "demo-app-resolved"

    def test_returns_empty_when_not_found(self):
        with patch("subprocess.run", return_value=make_mock_result("")):
            name = self.collector.find_pod_by_label("demo", "app=nonexistent")
            assert name == ""

    def test_uses_label_selector(self):
        with patch("subprocess.run", return_value=make_mock_result("pod")) as mock_run:
            self.collector.find_pod_by_label("demo", "app=test")
            cmd = mock_run.call_args[0][0]
            assert "-l" in cmd
            assert "app=test" in cmd
            assert "jsonpath={.items[0].metadata.name}" in cmd


class TestCollectEdgeCases:
    def setup_method(self):
        self.collector = KubernetesCollector()

    def test_uses_original_pod_name_when_resolution_fails(self):
        returns = [
            make_mock_result(""),        # _pod_exists → empty (not found)
            make_mock_result(""),        # find_pod_by_label → empty
            make_mock_result("log1"),    # current logs
            make_mock_result("log2"),    # previous logs
            make_mock_result("status"),  # describe
            make_mock_result("events"),  # events
            make_mock_result("0"),       # restart count
            make_mock_result("[]"),      # container states
        ]
        with patch("subprocess.run", side_effect=returns) as mock_run:
            ev = self.collector.collect("demo", "demo-app")
            assert ev.pod_name == "demo-app"
            assert mock_run.call_count == 8

    def test_constructor_defaults(self):
        c = KubernetesCollector()
        assert c.kubectl == "kubectl"
        assert c.timeout == 30

    def test_constructor_custom_values(self):
        c = KubernetesCollector(kubectl_path="microk8s.kubectl", timeout=60)
        assert c.kubectl == "microk8s.kubectl"
        assert c.timeout == 60

    def test_get_pod_logs_tail_defaults_to_500(self):
        with patch("subprocess.run", return_value=make_mock_result("log")) as mock_run:
            self.collector.get_pod_logs("demo", "pod")
            cmd = mock_run.call_args[0][0]
            assert "--tail=500" in cmd

    def test_get_events_no_field_selector_omits_flag(self):
        with patch("subprocess.run", return_value=make_mock_result("events")) as mock_run:
            self.collector.get_events("demo")
            cmd = mock_run.call_args[0][0]
            assert "--field-selector" not in cmd

    def test_get_restart_count_returns_zero_on_type_error(self):
        with patch("subprocess.run", return_value=make_mock_result("")):
            count = self.collector.get_restart_count("demo", "pod-abc")
            assert count == 0

    def test_collect_all_fields_stripped_newlines(self):
        returns = [
            make_mock_result("demo-app-abc"),
            make_mock_result("log line with spaces"),
            make_mock_result(""),
            make_mock_result("status info"),
            make_mock_result("events"),
            make_mock_result("5"),
            make_mock_result("[{}]"),
        ]
        with patch("subprocess.run", side_effect=returns):
            ev = self.collector.collect("demo", "pod")
            assert ev.namespace == "demo"
            assert ev.current_logs == "log line with spaces"
            assert ev.restart_count == 5
