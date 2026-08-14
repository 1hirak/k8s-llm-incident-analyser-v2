from unittest.mock import MagicMock, patch

import pytest
from app.manager import RemediationError, RemediationManager
from k8s_llm_shared import RemediationAction


def action(**overrides):
    data = {
        "action_type": "set_deployment_resources",
        "namespace": "demo",
        "deployment_name": "demo-app",
        "container_name": "demo-app",
        "memory_limit": "256Mi",
    }
    data.update(overrides)
    return RemediationAction(**data)


def ok_result(stdout="patched"):
    result = MagicMock()
    result.returncode = 0
    result.stdout = stdout
    result.stderr = ""
    return result


def test_build_patch_is_typed_and_bounded():
    patch = RemediationManager.build_patch(action())
    assert patch == {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "demo-app",
                            "resources": {"limits": {"memory": "256Mi"}},
                        }
                    ]
                }
            }
        }
    }


def test_dry_run_uses_server_side_dry_run():
    manager = RemediationManager(allowed_namespaces=("demo",))
    with patch("subprocess.run", return_value=ok_result("rendered")) as run:
        assert manager.dry_run(action()) == "rendered"
    command = run.call_args.args[0]
    assert "--dry-run=server" in command
    assert "--patch" in command
    assert "kubectl" == command[0]


def test_namespace_policy_is_enforced_before_kubectl():
    manager = RemediationManager(allowed_namespaces=("demo",))
    with patch("subprocess.run") as run:
        with pytest.raises(RemediationError, match="not allowed"):
            manager.dry_run(action(namespace="production"))
    run.assert_not_called()


def test_probe_requires_absolute_path():
    with pytest.raises(RemediationError, match="absolute path"):
        RemediationManager.build_patch(
            action(
                action_type="set_deployment_probe",
                probe_type="readiness",
                probe_path="health",
            )
        )
