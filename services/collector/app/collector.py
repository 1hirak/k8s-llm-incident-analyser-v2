"""Kubernetes evidence collector — wraps kubectl subprocess calls.

Moved from the monolith (app/core/collector.py). The only behavioural
change is that RawEvidence is now the shared Pydantic contract model
instead of a local dataclass.
"""

import json
import logging
import subprocess

from k8s_llm_shared import RawEvidence

logger = logging.getLogger(__name__)


class KubernetesCollector:
    def __init__(self, kubectl_path: str = "kubectl", timeout: int = 30):
        self.kubectl = kubectl_path
        self.timeout = timeout

    def check_connectivity(self) -> bool:
        try:
            result = subprocess.run(
                [self.kubectl, "version", "--client=false"],
                capture_output=True, text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _run(self, *args) -> str:
        cmd = [self.kubectl, *args]
        logger.debug("Running: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "kubectl returned %d: %s",
                    result.returncode, result.stderr[:200],
                )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error("kubectl timed out: %s", " ".join(cmd))
            return ""

    def get_pod_logs(
        self, namespace: str, pod: str, previous: bool = False, tail: int = 500
    ) -> str:
        args = [
            "logs", "-n", namespace, pod,
            f"--tail={tail}", "--timestamps=true",
        ]
        if previous:
            args.append("--previous")
        return self._run(*args)

    def get_pod_description(self, namespace: str, pod: str) -> str:
        return self._run("describe", "pod", "-n", namespace, pod)

    def get_events(self, namespace: str, field_selector: str = "") -> str:
        args = [
            "get", "events", "-n", namespace,
            "--sort-by=.metadata.creationTimestamp",
        ]
        if field_selector:
            args.append(f"--field-selector={field_selector}")
        return self._run(*args)

    def get_restart_count(self, namespace: str, pod: str) -> int:
        raw = self._run(
            "get", "pod", "-n", namespace, pod,
            "-o", "jsonpath={.status.containerStatuses[0].restartCount}",
        )
        try:
            return int(raw)
        except (ValueError, TypeError):
            return 0

    def get_container_states(self, namespace: str, pod: str) -> list:
        raw = self._run(
            "get", "pod", "-n", namespace, pod,
            "-o", "jsonpath={.status.containerStatuses}",
        )
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else [parsed]

    def _pod_exists(self, namespace: str, pod: str) -> bool:
        """Check if a pod with the exact name exists."""
        raw = self._run(
            "get", "pod", "-n", namespace, pod,
            "-o", "jsonpath={.metadata.name}", "--ignore-not-found",
        )
        return bool(raw)

    def find_pod_by_label(self, namespace: str, label: str) -> str:
        """Find the first pod matching a label selector.

        Args:
            namespace: Kubernetes namespace.
            label: Label selector (e.g. "app=demo-app").

        Returns:
            Pod name, or empty string if not found.
        """
        return self._run(
            "get", "pods", "-n", namespace, "-l", label,
            "-o", "jsonpath={.items[0].metadata.name}",
        )

    def collect(self, namespace: str, pod_name: str) -> RawEvidence:
        logger.info("Collecting evidence for %s/%s", namespace, pod_name)
        actual_pod = pod_name
        if not self._pod_exists(namespace, pod_name):
            resolved = self.find_pod_by_label(namespace, f"app={pod_name}")
            if resolved:
                logger.info("Resolved %s -> %s", pod_name, resolved)
                actual_pod = resolved
        return RawEvidence(
            namespace=namespace,
            pod_name=actual_pod,
            current_logs=self.get_pod_logs(namespace, actual_pod, previous=False),
            previous_logs=self.get_pod_logs(namespace, actual_pod, previous=True),
            pod_status=self.get_pod_description(namespace, actual_pod),
            k8s_events=self.get_events(namespace),
            restart_count=self.get_restart_count(namespace, actual_pod),
            container_states=self.get_container_states(namespace, actual_pod),
        )
