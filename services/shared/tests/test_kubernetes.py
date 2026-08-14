import json
from pathlib import Path

import pytest
from k8s_llm_shared.kubernetes import KubernetesConfigurationError, configure_kubectl


def test_external_mode_requires_explicit_kubeconfig(monkeypatch):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.setenv("KUBERNETES_AUTH_MODE", "external")
    with pytest.raises(KubernetesConfigurationError, match="KUBECONFIG"):
        configure_kubectl()


def test_in_cluster_mode_creates_token_file_kubeconfig(tmp_path: Path, monkeypatch):
    token = tmp_path / "token"
    ca = tmp_path / "ca.crt"
    config = tmp_path / "config.json"
    token.write_text("token-value")
    ca.write_text("ca")
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.setenv("KUBERNETES_AUTH_MODE", "in-cluster")
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT_HTTPS", "6443")
    monkeypatch.setenv("K8S_SERVICE_ACCOUNT_TOKEN_FILE", str(token))
    monkeypatch.setenv("K8S_SERVICE_ACCOUNT_CA_FILE", str(ca))
    monkeypatch.setenv("IN_CLUSTER_KUBECONFIG", str(config))

    connection = configure_kubectl()

    assert connection.mode == "in-cluster"
    assert connection.server == "https://10.0.0.1:6443"
    payload = json.loads(config.read_text())
    assert payload["users"][0]["user"]["tokenFile"] == str(token)
    assert payload["clusters"][0]["cluster"]["certificate-authority"] == str(ca)
    assert config.stat().st_mode & 0o777 == 0o600
