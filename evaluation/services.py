"""HTTP adapters between the evaluation harness and the microservices stack.

The harness keeps its dependency-injection design: anything with a
``collect`` / ``process`` / ``redact`` / ``analyse`` method works. These
adapters implement those interfaces by calling the running services over
HTTP (docker-compose or locally forwarded ports).

Pipeline mapping:
    collector-svc  POST /collect   → RawEvidence
    processor-svc  POST /process   → EvidencePackage (already redacted)
    llm-svc        POST /analyse   → IncidentReport

Because processor-svc performs preprocessing AND redaction in a single
call, the redactor adapter in HTTP mode is a pass-through.
"""

from __future__ import annotations

import os

import httpx
from k8s_llm_shared import EvidencePackage, IncidentReport, RawEvidence

DEFAULT_COLLECTOR_URL = os.environ.get("COLLECTOR_URL", "http://localhost:8002")
DEFAULT_PROCESSOR_URL = os.environ.get("PROCESSOR_URL", "http://localhost:8003")
DEFAULT_LLM_URL = os.environ.get("LLM_URL", "http://localhost:8004")


class ServiceUnavailableError(RuntimeError):
    pass


class ServiceCollector:
    """Duck-type of the monolith KubernetesCollector over HTTP."""

    def __init__(self, base_url: str = DEFAULT_COLLECTOR_URL, timeout: float = 60):
        self._url = base_url.rstrip("/")
        self._timeout = timeout

    def collect(self, namespace: str, pod_name: str) -> RawEvidence:
        resp = httpx.post(
            f"{self._url}/collect",
            json={"namespace": namespace, "pod_name": pod_name},
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise ServiceUnavailableError(
                f"collector-svc returned {resp.status_code}: {resp.text[:200]}"
            )
        return RawEvidence(**resp.json())


class ServicePreprocessor:
    """Duck-type of the monolith LogPreprocessor over HTTP."""

    def __init__(self, base_url: str = DEFAULT_PROCESSOR_URL, timeout: float = 30):
        self._url = base_url.rstrip("/")
        self._timeout = timeout

    def process(self, evidence: RawEvidence) -> EvidencePackage:
        resp = httpx.post(
            f"{self._url}/process",
            json=evidence.model_dump(),
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise ServiceUnavailableError(
                f"processor-svc returned {resp.status_code}: {resp.text[:200]}"
            )
        return EvidencePackage(**resp.json())


class PassThroughRedactor:
    """processor-svc already redacts — HTTP-mode redaction is a no-op."""

    def redact(self, package: EvidencePackage) -> EvidencePackage:
        return package


class ServiceLLMProvider:
    """Duck-type of a monolith BaseLLMProvider over HTTP."""

    def __init__(self, base_url: str = DEFAULT_LLM_URL, timeout: float = 90):
        self._url = base_url.rstrip("/")
        self._timeout = timeout

    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._url}/analyse",
                json=package.model_dump(),
                timeout=self._timeout,
            )
        if resp.status_code != 200:
            raise ServiceUnavailableError(
                f"llm-svc returned {resp.status_code}: {resp.text[:200]}"
            )
        return IncidentReport(**resp.json())
