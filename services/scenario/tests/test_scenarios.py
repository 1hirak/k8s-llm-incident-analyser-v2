"""Unit tests for the scenario manager."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.scenarios import (
    KubectlError,
    ScenarioConflictError,
    ScenarioManager,
    ScenarioNotFoundError,
    _humanize_name,
    _parse_patch_target,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIOS_DIR = REPO_ROOT / "k8s" / "scenarios"
BASE_DIR = REPO_ROOT / "k8s" / "base"
GROUND_TRUTH_DIR = REPO_ROOT / "evaluation" / "ground_truth"


def make_manager(**kwargs) -> ScenarioManager:
    defaults = {
        "scenarios_dir": str(SCENARIOS_DIR),
        "base_dir": str(BASE_DIR),
        "namespace": "demo",
        "ground_truth_dir": str(GROUND_TRUTH_DIR),
    }
    defaults.update(kwargs)
    return ScenarioManager(**defaults)


def ok_result(stdout="patched"):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = 0
    return m


def err_result(stderr="boom", returncode=1):
    m = MagicMock()
    m.stdout = ""
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestListScenarios:
    def test_lists_all_repo_scenarios(self):
        manager = make_manager()
        scenarios = manager.list_scenarios()
        ids = [s.scenario_id for s in scenarios]
        assert len(ids) == 25
        assert "05-oom" in ids
        assert ids == sorted(ids)

    def test_metadata_from_ground_truth(self):
        manager = make_manager()
        scenarios = {s.scenario_id: s for s in manager.list_scenarios()}
        oom = scenarios["05-oom"]
        assert oom.category == "resource"
        assert oom.severity == "high"
        assert "memory" in oom.description.lower()

    def test_fallback_metadata_without_ground_truth(self, tmp_path):
        (tmp_path / "99-test-fault").mkdir()
        (tmp_path / "99-test-fault" / "fault.yaml").write_text(
            "kind: Deployment\nmetadata:\n  name: demo-app\n"
        )
        manager = make_manager(
            scenarios_dir=str(tmp_path), ground_truth_dir=str(tmp_path / "none")
        )
        scenarios = manager.list_scenarios()
        assert len(scenarios) == 1
        s = scenarios[0]
        assert s.scenario_id == "99-test-fault"
        assert s.category == "unknown"
        assert s.name == "Test Fault"

    def test_empty_when_dir_missing(self, tmp_path):
        manager = make_manager(scenarios_dir=str(tmp_path / "nope"))
        assert manager.list_scenarios() == []


class TestApply:
    def test_apply_patches_deployment(self):
        manager = make_manager()
        with patch("subprocess.run", return_value=ok_result()) as mock_run:
            desc = manager.apply("05-oom")
        assert manager.active_scenarios == {"05-oom"}
        assert "memory" in desc.lower()
        cmd = mock_run.call_args[0][0]
        assert "patch" in cmd
        assert "deployment/demo-app" in cmd
        assert "--type" in cmd and "strategic" in cmd

    def test_apply_unknown_scenario_raises_not_found(self):
        manager = make_manager()
        with pytest.raises(ScenarioNotFoundError):
            manager.apply("99-nonexistent")

    def test_apply_allows_multiple_different_scenarios(self):
        manager = make_manager()
        with patch("subprocess.run", return_value=ok_result()):
            manager.apply("05-oom")
            manager.apply("03-crashloop")
        assert manager.active_scenarios == {"05-oom", "03-crashloop"}

    def test_apply_same_scenario_twice_raises_conflict(self):
        manager = make_manager()
        with patch("subprocess.run", return_value=ok_result()):
            manager.apply("05-oom")
            with pytest.raises(ScenarioConflictError):
                manager.apply("05-oom")

    def test_apply_kubectl_failure_raises(self):
        manager = make_manager()
        with patch("subprocess.run", return_value=err_result()):
            with pytest.raises(KubectlError):
                manager.apply("05-oom")
        assert manager.active_scenarios == set()


class TestReset:
    def test_reset_clears_active_and_applies_base(self):
        manager = make_manager()
        with patch("subprocess.run", return_value=ok_result()) as mock_run:
            manager.apply("05-oom")
            manager.reset()
        assert manager.active_scenarios == set()
        cmds = [call[0][0] for call in mock_run.call_args_list]
        # delete deployment, apply base files, rollout status
        assert any("delete" in c and "deployment" in c for c in cmds)
        assert any("apply" in c for c in cmds)
        assert any("rollout" in c and "status" in c for c in cmds)

    def test_reset_kubectl_failure_raises(self):
        manager = make_manager()
        with patch("subprocess.run", return_value=err_result()):
            with pytest.raises(KubectlError):
                manager.reset()


class TestHelpers:
    def test_humanize_name(self):
        assert _humanize_name("05-oom") == "Oom"
        assert _humanize_name("01-missing-env") == "Missing Env"
        assert _humanize_name("10-wrong-port") == "Wrong Port"

    def test_parse_patch_target(self):
        patch_text = (
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n"
            "  name: demo-app\n  namespace: demo\n"
        )
        kind, name = _parse_patch_target(patch_text)
        assert kind == "deployment"
        assert name == "demo-app"

    def test_parse_patch_target_defaults(self):
        kind, name = _parse_patch_target("spec: {}")
        assert kind == "deployment"
        assert name == "demo-app"
