"""Build and execute the small, typed remediation action set."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

from k8s_llm_shared import RemediationAction
from k8s_llm_shared.kubernetes import KubernetesConnection, configure_kubectl


class RemediationError(RuntimeError):
    """A Kubernetes dry-run or apply operation failed."""


class RemediationManager:
    def __init__(
        self,
        *,
        allowed_namespaces: tuple[str, ...] = ("demo",),
        kubectl_path: str = "kubectl",
        timeout: int = 120,
    ):
        self.connection: KubernetesConnection = configure_kubectl()
        self.kubectl = os.environ.get("KUBECTL_PATH", kubectl_path)
        self.allowed_namespaces = allowed_namespaces
        self.timeout = timeout

    def _command(self, *args: str) -> list[str]:
        command = [self.kubectl]
        context = os.environ.get("KUBE_CONTEXT") or os.environ.get(
            "KUBERNETES_CONTEXT"
        )
        if context:
            command.extend(["--context", context])
        command.extend(args)
        return command

    def _validate_namespace(self, action: RemediationAction) -> None:
        if "*" not in self.allowed_namespaces and action.namespace not in self.allowed_namespaces:
            raise RemediationError(
                f"Remediation is not allowed in namespace '{action.namespace}'"
            )

    @staticmethod
    def _require_container(action: RemediationAction) -> str:
        if not action.container_name:
            raise RemediationError(
                f"container_name is required for {action.action_type}"
            )
        return action.container_name

    @staticmethod
    def build_patch(action: RemediationAction) -> dict:
        """Translate the typed action into a bounded strategic merge patch."""
        if action.action_type == "rollout_restart":
            timestamp = datetime.now(timezone.utc).isoformat()
            return {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {"k8s-llm.io/restarted-at": timestamp}
                        }
                    }
                }
            }

        container_name = RemediationManager._require_container(action)
        container: dict = {"name": container_name}
        if action.action_type == "set_deployment_image":
            if not action.image or any(char in action.image for char in "\r\n"):
                raise RemediationError("A single-line image is required")
            container["image"] = action.image
        elif action.action_type == "set_deployment_resources":
            requests = {}
            limits = {}
            if action.cpu_request:
                requests["cpu"] = action.cpu_request
            if action.memory_request:
                requests["memory"] = action.memory_request
            if action.cpu_limit:
                limits["cpu"] = action.cpu_limit
            if action.memory_limit:
                limits["memory"] = action.memory_limit
            if not requests and not limits:
                raise RemediationError("At least one resource request or limit is required")
            container["resources"] = {}
            if requests:
                container["resources"]["requests"] = requests
            if limits:
                container["resources"]["limits"] = limits
        elif action.action_type == "set_deployment_probe":
            if action.probe_type is None or not action.probe_path:
                raise RemediationError("probe_type and probe_path are required")
            if not action.probe_path.startswith("/") or any(
                char in action.probe_path for char in "\r\n"
            ):
                raise RemediationError("probe_path must be a single absolute path")
            container[action.probe_type + "Probe"] = {
                "httpGet": {"path": action.probe_path}
            }
        else:
            raise RemediationError(f"Unsupported remediation action: {action.action_type}")
        return {"spec": {"template": {"spec": {"containers": [container]}}}}

    def _run(self, *args: str, timeout: int | None = None) -> str:
        result = subprocess.run(
            self._command(*args),
            capture_output=True,
            text=True,
            timeout=timeout or self.timeout,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[:500]
            raise RemediationError(detail or "kubectl command failed")
        return result.stdout.strip()

    def dry_run(self, action: RemediationAction) -> str:
        self._validate_namespace(action)
        patch = json.dumps(self.build_patch(action), separators=(",", ":"))
        return self._run(
            "patch",
            f"deployment/{action.deployment_name}",
            "-n",
            action.namespace,
            "--type",
            "strategic",
            "--patch",
            patch,
            "--dry-run=server",
            "-o",
            "yaml",
            timeout=30,
        )

    def apply(self, action: RemediationAction) -> str:
        self._validate_namespace(action)
        patch = json.dumps(self.build_patch(action), separators=(",", ":"))
        applied = self._run(
            "patch",
            f"deployment/{action.deployment_name}",
            "-n",
            action.namespace,
            "--type",
            "strategic",
            "--patch",
            patch,
        )
        rollout = self._run(
            "rollout",
            "status",
            f"deployment/{action.deployment_name}",
            "-n",
            action.namespace,
            "--timeout=120s",
        )
        return "\n".join(part for part in (applied, rollout) if part)

    def check_connectivity(self) -> bool:
        try:
            result = subprocess.run(
                self._command("version", "--client=false"),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
