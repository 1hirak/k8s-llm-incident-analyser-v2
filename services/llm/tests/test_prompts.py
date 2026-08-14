from app.prompts import build_prompt
from k8s_llm_shared import EvidencePackage


class TestBuildPrompt:
    def _make_package(self, **kwargs) -> EvidencePackage:
        defaults = {
            "namespace": "demo",
            "pod_name": "demo-app-abc",
            "current_logs": "ERROR Missing DATABASE_URL",
            "previous_logs": "WARN previous startup log",
            "pod_status_summary": "Status: CrashLoopBackOff",
            "k8s_events_filtered": "Warning BackOff restarting",
            "restart_count": 3,
        }
        defaults.update(kwargs)
        return EvidencePackage(**defaults)

    def test_build_prompt_returns_tuple(self):
        result = build_prompt(self._make_package())
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_contains_rules(self):
        system, user = build_prompt(self._make_package())
        assert "Kubernetes incident analyst" in system
        assert "Only use evidence that is present" in system
        assert "valid JSON object" in system
        assert "Never recommend automated remediation" in system
        assert "hidden chain-of-thought" in system
        assert "analysis_explanation" in system

    def test_user_prompt_contains_evidence_fields(self):
        pkg = self._make_package()
        system, user = build_prompt(pkg)
        assert "demo" in user
        assert "demo-app-abc" in user
        assert "ERROR Missing DATABASE_URL" in user
        assert "CrashLoopBackOff" in user

    def test_user_prompt_does_not_duplicate_json_schema(self):
        system, user = build_prompt(self._make_package())
        assert "incident_summary" not in user
        assert "likely_root_cause" not in user
        assert "failure_category" not in user

    def test_user_prompt_empty_logs_handled(self):
        pkg = self._make_package(current_logs="", previous_logs="(none)")
        system, user = build_prompt(pkg)
        assert "(none)" in user

    def test_user_prompt_includes_restart_count(self):
        pkg = self._make_package(restart_count=5)
        system, user = build_prompt(pkg)
        assert "5" in user

    def test_system_prompt_is_stable_for_cache(self):
        system, user = build_prompt(self._make_package())
        assert "incident_summary" not in user
        assert "Collection Time:" not in user

    def test_system_prompt_consistent(self):
        s1, _ = build_prompt(self._make_package(namespace="ns1"))
        s2, _ = build_prompt(self._make_package(namespace="ns2"))
        assert s1 == s2

    def test_user_prompt_contains_pod_status_fallback(self):
        pkg = self._make_package(pod_status_summary="")
        system, user = build_prompt(pkg)
        assert "no pod status available" in user

    def test_user_prompt_contains_events_fallback(self):
        pkg = self._make_package(k8s_events_filtered="")
        system, user = build_prompt(pkg)
        assert "no kubernetes events" in user

    def test_user_prompt_contains_current_logs_fallback(self):
        pkg = self._make_package(current_logs="")
        system, user = build_prompt(pkg)
        assert "no current logs" in user

    def test_user_prompt_contains_previous_logs_fallback(self):
        pkg = self._make_package(previous_logs="")
        system, user = build_prompt(pkg)
        assert "no previous logs" in user

    def test_json_schema_fields_are_added_by_provider(self):
        system, user = build_prompt(self._make_package())
        assert "failure_category" not in user
        assert "severity" not in user
        assert "confidence" not in user
        assert "supporting_evidence" not in user
        assert "recommended_commands" not in user
        assert "human_verification_steps" not in user
        assert "uncertainty" not in user

    def test_build_prompt_handles_zero_restart_count(self):
        pkg = self._make_package(restart_count=0)
        system, user = build_prompt(pkg)
        assert "0" in user
