"""Kubernetes evidence collector — wraps kubectl subprocess calls.

Moved from the monolith (app/core/collector.py). The only behavioural
change is that RawEvidence is now the shared Pydantic contract model
instead of a local dataclass.
"""

import json
import logging
import os
import subprocess

from k8s_llm_shared import RawEvidence
from k8s_llm_shared.enums import TargetKind
from k8s_llm_shared.kubernetes import (
    KubernetesConnection,
    configure_kubectl,
)

logger = logging.getLogger(__name__)

RESOURCE_NAMES = {
    "Pod": "pods",
    "Deployment": "deployments",
    "ReplicaSet": "replicasets",
    "StatefulSet": "statefulsets",
    "DaemonSet": "daemonsets",
    "Job": "jobs",
    "CronJob": "cronjobs",
    "Service": "services",
    "Namespace": "namespaces",
    "Node": "nodes",
}


class KubernetesCollector:
    def __init__(self, kubectl_path: str = "kubectl", timeout: int = 30):
        self.connection: KubernetesConnection = configure_kubectl()
        self.kubectl = os.environ.get("KUBECTL_PATH", kubectl_path)
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

    def check_connectivity(self) -> bool:
        try:
            result = subprocess.run(
                self._command("version", "--client=false"),
                capture_output=True, text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def check_permission(
        self, verb: str, resource: str, namespace: str | None = None
    ) -> bool:
        args = ["auth", "can-i", verb, resource]
        if namespace:
            args.extend(["-n", namespace])
        try:
            result = subprocess.run(
                self._command(*args),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0 and result.stdout.strip().lower() == "yes"
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def connection_status(self, namespace: str = "demo") -> dict:
        connected = self.check_connectivity()
        permissions = {
            "get_pods": False,
            "get_pod_logs": False,
            "get_events": False,
        }
        if connected:
            permissions = {
                "get_pods": self.check_permission("get", "pods", namespace),
                "get_pod_logs": self.check_permission("get", "pods/log", namespace),
                "get_events": self.check_permission("get", "events", namespace),
            }
        return {
            "cluster": "connected" if connected else "unreachable",
            "mode": self.connection.mode,
            "kubeconfig": self.connection.kubeconfig,
            "context": self.connection.context,
            "server": self.connection.server,
            "namespace": namespace,
            "permissions": permissions,
        }

    def _run(self, *args) -> str:
        cmd = self._command(*args)
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
        args = ["get", "events"]
        if namespace not in ("all", "*"):
            args.extend(["-n", namespace])
        else:
            args.append("-A")
        args.append("--sort-by=.metadata.creationTimestamp")
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

    def _get_json(
        self, resource: str, name: str | None = None, namespace: str | None = None
    ) -> dict:
        args = ["get", resource]
        if name:
            args.append(name)
        if namespace and namespace not in ("all", "*"):
            args.extend(["-n", namespace])
        elif not namespace and resource not in ("namespaces", "nodes"):
            args.append("-A")
        args.extend(["-o", "json"])
        raw = self._run(*args)
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def list_targets(self, kind: TargetKind, namespace: str | None = None) -> list[dict]:
        """Return names that can be selected in the diagnosis UI."""
        resource = RESOURCE_NAMES[kind]
        raw = self._get_json(resource, namespace=namespace)
        items = raw.get("items", [])
        if not isinstance(items, list):
            return []
        return [
            {
                "name": item.get("metadata", {}).get("name", ""),
                "kind": kind,
                "namespace": item.get("metadata", {}).get("namespace")
                or (namespace if kind not in ("Namespace", "Node") else None),
            }
            for item in items
            if item.get("metadata", {}).get("name")
        ]

    def _list_pods(
        self,
        namespace: str | None,
        *,
        selector: str | None = None,
        field_selector: str | None = None,
    ) -> list[dict]:
        args = ["get", "pods"]
        if namespace and namespace not in ("all", "*"):
            args.extend(["-n", namespace])
        else:
            args.append("-A")
        if selector:
            args.extend(["-l", selector])
        if field_selector:
            args.append(f"--field-selector={field_selector}")
        args.extend(["-o", "json"])
        raw = self._run(*args)
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        items = parsed.get("items", []) if isinstance(parsed, dict) else []
        return items if isinstance(items, list) else []

    @staticmethod
    def _label_selector(selector: object) -> str:
        if isinstance(selector, str):
            return selector
        if isinstance(selector, dict):
            labels = selector.get("matchLabels", {})
            if isinstance(labels, dict):
                return ",".join(f"{key}={value}" for key, value in labels.items())
        return ""

    def _related_pods(
        self, namespace: str, kind: TargetKind, name: str
    ) -> list[dict]:
        if kind == "Namespace":
            return self._list_pods(name)
        if kind == "Node":
            return self._list_pods("all", field_selector=f"spec.nodeName={name}")
        if kind == "Pod":
            exact = self._get_json("pod", name, namespace)
            if exact.get("metadata", {}).get("name"):
                return [exact]
            resolved = self.find_pod_by_label(namespace, f"app={name}")
            return [self._get_json("pod", resolved, namespace)] if resolved else []

        resource = RESOURCE_NAMES[kind]
        target = self._get_json(resource[:-1] if resource.endswith("s") else resource, name, namespace)
        selector = self._label_selector(target.get("spec", {}).get("selector"))
        if selector:
            return self._list_pods(namespace, selector=selector)

        if kind == "CronJob":
            job_data = self._get_json("jobs", namespace=namespace)
            job_names = []
            for job in job_data.get("items", []):
                owners = job.get("metadata", {}).get("ownerReferences", [])
                if any(owner.get("kind") == "CronJob" and owner.get("name") == name for owner in owners):
                    job_names.append(job.get("metadata", {}).get("name"))
            pods = []
            for job_name in job_names:
                pods.extend(self._list_pods(namespace, selector=f"job-name={job_name}"))
            return pods

        return self._list_pods(namespace, selector=f"{kind.lower()}-name={name}")

    def _collect_target(self, namespace: str, kind: TargetKind, name: str) -> RawEvidence:
        pods = [pod for pod in self._related_pods(namespace, kind, name) if pod.get("metadata", {}).get("name")]
        pod_refs = [
            (
                pod.get("metadata", {}).get("namespace") or namespace,
                pod.get("metadata", {}).get("name"),
            )
            for pod in pods
        ]
        resource = RESOURCE_NAMES[kind]
        target_description = self._run(
            "describe", resource[:-1] if resource.endswith("s") else resource,
            name,
            *([] if kind in ("Namespace", "Node") else ["-n", namespace]),
        )
        current_logs = []
        previous_logs = []
        pod_status = [f"Target: {kind}/{name}", target_description]
        container_states = []
        restart_count = 0
        for pod_namespace, pod_name in pod_refs[:10]:
            current = self.get_pod_logs(pod_namespace, pod_name, previous=False, tail=200)
            previous = self.get_pod_logs(pod_namespace, pod_name, previous=True, tail=200)
            current_logs.append(f"[{pod_namespace}/{pod_name}]\n{current}")
            if previous:
                previous_logs.append(f"[{pod_namespace}/{pod_name}]\n{previous}")
            pod_status.append(f"--- Pod {pod_namespace}/{pod_name} ---\n{self.get_pod_description(pod_namespace, pod_name)}")
            restart_count += self.get_restart_count(pod_namespace, pod_name)
            container_states.extend(self.get_container_states(pod_namespace, pod_name))

        target_context = (
            f"Target kind: {kind}\nTarget name: {name}\n"
            f"Related pods: {', '.join(f'{ns}/{pod}' for ns, pod in pod_refs) or '(none)'}\n"
            f"{target_description}"
        )
        event_parts = [
            self.get_events(
                namespace,
                field_selector=f"involvedObject.name={name}",
            )
        ]
        for pod_namespace, pod_name in pod_refs[:10]:
            event_parts.append(
                self.get_events(
                    pod_namespace,
                    field_selector=f"involvedObject.name={pod_name}",
                )
            )
        return RawEvidence(
            namespace=namespace,
            pod_name=name,
            target_kind=kind,
            target_name=name,
            target_context=target_context[:12000],
            pod_names=[pod for _, pod in pod_refs],
            current_logs="\n\n".join(current_logs)[:12000],
            previous_logs="\n\n".join(previous_logs)[:12000],
            pod_status="\n\n".join(pod_status)[:12000],
            k8s_events="\n\n".join(part for part in event_parts if part),
            restart_count=restart_count,
            container_states=container_states,
        )

    def collect(
        self, namespace: str, pod_name: str, target_kind: TargetKind = "Pod"
    ) -> RawEvidence:
        if target_kind != "Pod":
            return self._collect_target(namespace, target_kind, pod_name)
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
            target_kind="Pod",
            target_name=actual_pod,
            target_context=f"Target kind: Pod\nTarget name: {actual_pod}",
            pod_names=[actual_pod],
            current_logs=self.get_pod_logs(namespace, actual_pod, previous=False),
            previous_logs=self.get_pod_logs(namespace, actual_pod, previous=True),
            pod_status=self.get_pod_description(namespace, actual_pod),
            k8s_events=self.get_events(
                namespace,
                field_selector=f"involvedObject.name={actual_pod}",
            ),
            restart_count=self.get_restart_count(namespace, actual_pod),
            container_states=self.get_container_states(namespace, actual_pod),
        )
