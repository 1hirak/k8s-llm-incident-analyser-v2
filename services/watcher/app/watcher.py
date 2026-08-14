"""Read-only Kubernetes scanner used by watcher-svc."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from k8s_llm_shared.kubernetes import KubernetesConnection, configure_kubectl

UNHEALTHY_WAITING_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "CreateContainerError",
    "InvalidImageName",
    "RunContainerError",
}


@dataclass(frozen=True)
class DetectedIncident:
    namespace: str
    pod_name: str
    reason: str
    signature: str
    restart_count: int

    def as_job_request(self) -> dict[str, str]:
        return {
            "namespace": self.namespace,
            "pod_name": self.pod_name,
            "target_kind": "Pod",
        }


class KubernetesWatcher:
    """Scan pod status without requesting secrets or write permissions."""

    def __init__(
        self,
        *,
        namespaces: tuple[str, ...] = ("demo",),
        restart_threshold: int = 3,
        timeout: int = 30,
        kubectl_path: str = "kubectl",
    ):
        self.connection: KubernetesConnection = configure_kubectl()
        self.kubectl = os.environ.get("KUBECTL_PATH", kubectl_path)
        self.namespaces = namespaces
        self.restart_threshold = restart_threshold
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

    def _list_pods(self) -> list[dict[str, Any]]:
        args = ["get", "pods"]
        if self.namespaces and "*" not in self.namespaces:
            # One request per namespace keeps the required RBAC scope
            # namespace-specific and avoids requiring a cluster-wide list.
            payloads = []
            for namespace in self.namespaces:
                payloads.append(self._get_pods_for_namespace(args, namespace))
            return [item for payload in payloads for item in payload]
        return self._get_pods_for_namespace(args, None)

    def _get_pods_for_namespace(
        self, base_args: list[str], namespace: str | None
    ) -> list[dict[str, Any]]:
        args = [*base_args]
        if namespace:
            args.extend(["-n", namespace])
        else:
            args.append("-A")
        args.extend(["-o", "json"])
        try:
            result = subprocess.run(
                self._command(*args),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return []
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return items if isinstance(items, list) else []

    def scan(self) -> list[DetectedIncident]:
        incidents: list[DetectedIncident] = []
        for pod in self._list_pods():
            metadata = pod.get("metadata") or {}
            status = pod.get("status") or {}
            namespace = metadata.get("namespace")
            pod_name = metadata.get("name")
            if not namespace or not pod_name:
                continue

            reasons: list[str] = []
            restart_count = 0
            for container in [
                *(status.get("initContainerStatuses") or []),
                *(status.get("containerStatuses") or []),
            ]:
                restart_count += int(container.get("restartCount") or 0)
                waiting = (container.get("state") or {}).get("waiting") or {}
                terminated = (container.get("lastState") or {}).get("terminated") or {}
                waiting_reason = waiting.get("reason")
                terminated_reason = terminated.get("reason")
                if waiting_reason in UNHEALTHY_WAITING_REASONS:
                    reasons.append(str(waiting_reason))
                if terminated_reason == "OOMKilled":
                    reasons.append("OOMKilled")

            for condition in status.get("conditions") or []:
                if condition.get("reason") == "Unschedulable":
                    reasons.append("Unschedulable")

            if restart_count >= self.restart_threshold:
                reasons.append("RepeatedRestarts")
            if not reasons and status.get("phase") == "Failed":
                reasons.append("Failed")
            if not reasons:
                continue

            reason = reasons[0]
            signature = ":".join(sorted(set(reasons)))
            incidents.append(
                DetectedIncident(
                    namespace=namespace,
                    pod_name=pod_name,
                    reason=reason,
                    signature=signature,
                    restart_count=restart_count,
                )
            )
        return incidents

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
