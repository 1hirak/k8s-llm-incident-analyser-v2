"""Kubernetes credential bootstrap shared by cluster-facing services.

The services still use ``kubectl`` for collection and mutation, but they no
longer depend on kubectl guessing how credentials should be loaded. External
deployments provide ``KUBECONFIG`` explicitly. In-cluster deployments use the
projected ServiceAccount token and CA to create a small kubeconfig at runtime.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
DEFAULT_IN_CLUSTER_KUBECONFIG = "/tmp/k8s-llm-incluster-kubeconfig.json"


class KubernetesConfigurationError(RuntimeError):
    """Raised when an explicitly requested Kubernetes auth mode is invalid."""


@dataclass(frozen=True)
class KubernetesConnection:
    """Resolved kubectl connection settings for health and diagnostics."""

    mode: str
    kubeconfig: str | None
    context: str | None
    server: str | None


def _write_in_cluster_kubeconfig() -> tuple[str, str]:
    token_file = Path(
        os.environ.get("K8S_SERVICE_ACCOUNT_TOKEN_FILE", SERVICE_ACCOUNT_DIR / "token")
    )
    ca_file = Path(
        os.environ.get("K8S_SERVICE_ACCOUNT_CA_FILE", SERVICE_ACCOUNT_DIR / "ca.crt")
    )
    if not token_file.is_file():
        raise KubernetesConfigurationError(
            f"ServiceAccount token was not found at {token_file}"
        )
    if not ca_file.is_file():
        raise KubernetesConfigurationError(
            f"Kubernetes CA certificate was not found at {ca_file}"
        )

    host = os.environ.get("KUBERNETES_SERVICE_HOST")
    if not host:
        raise KubernetesConfigurationError(
            "KUBERNETES_SERVICE_HOST is not set; cannot configure in-cluster auth"
        )
    port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    server = os.environ.get("K8S_API_SERVER", f"https://{host}:{port}")
    path = Path(
        os.environ.get("IN_CLUSTER_KUBECONFIG", DEFAULT_IN_CLUSTER_KUBECONFIG)
    )
    path.parent.mkdir(parents=True, exist_ok=True)

    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [
            {
                "name": "in-cluster",
                "cluster": {
                    "server": server,
                    "certificate-authority": str(ca_file),
                },
            }
        ],
        "users": [
            {
                "name": "service-account",
                "user": {"tokenFile": str(token_file)},
            }
        ],
        "contexts": [
            {
                "name": "in-cluster",
                "context": {
                    "cluster": "in-cluster",
                    "user": "service-account",
                    "namespace": os.environ.get("POD_NAMESPACE", "default"),
                },
            }
        ],
        "current-context": "in-cluster",
    }
    path.write_text(json.dumps(config), encoding="utf-8")
    os.chmod(path, 0o600)
    return str(path), server


def configure_kubectl() -> KubernetesConnection:
    """Configure kubectl from an external kubeconfig or in-cluster identity.

    ``KUBERNETES_AUTH_MODE`` accepts ``auto`` (the default), ``external``, or
    ``in-cluster``. The function is idempotent and only writes a file for the
    in-cluster mode.
    """

    requested_mode = os.environ.get("KUBERNETES_AUTH_MODE", "auto").lower()
    if requested_mode not in {"auto", "external", "in-cluster"}:
        raise KubernetesConfigurationError(
            "KUBERNETES_AUTH_MODE must be auto, external, or in-cluster"
        )

    context = os.environ.get("KUBE_CONTEXT") or os.environ.get(
        "KUBERNETES_CONTEXT"
    )
    kubeconfig = os.environ.get("KUBECONFIG")
    server = os.environ.get("K8S_API_SERVER")

    if requested_mode == "external" and not kubeconfig:
        raise KubernetesConfigurationError(
            "KUBECONFIG is required when KUBERNETES_AUTH_MODE=external"
        )

    if not kubeconfig and requested_mode == "auto":
        default_config = Path.home() / ".kube" / "config"
        if default_config.is_file():
            kubeconfig = str(default_config)

    in_cluster_available = bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
    if not kubeconfig and requested_mode in {"auto", "in-cluster"} and in_cluster_available:
        kubeconfig, server = _write_in_cluster_kubeconfig()
        resolved_mode = "in-cluster"
    elif kubeconfig:
        resolved_mode = "external"
    elif requested_mode == "in-cluster":
        raise KubernetesConfigurationError(
            "in-cluster Kubernetes environment variables are unavailable"
        )
    else:
        resolved_mode = "unconfigured"

    if kubeconfig:
        os.environ["KUBECONFIG"] = kubeconfig
    return KubernetesConnection(
        mode=resolved_mode,
        kubeconfig=kubeconfig,
        context=context,
        server=server,
    )
