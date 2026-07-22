"""llm-svc — LLM analysis service.

Implements contracts/api/llm.yaml. Owns all LLM provider integrations
(mock, openai, anthropic, deepseek), prompt building, and structured
output validation. The only service that holds external LLM API keys.
"""

import os

import structlog
from fastapi import FastAPI, HTTPException
from k8s_llm_shared import EvidencePackage, IncidentReport, ProviderInfo
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.llm import get_provider
from app.validator import ReportValidator

log = structlog.get_logger()

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "mock").lower()

_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "deepseek": "deepseek-chat",
    "mock": "(none)",
}

_PROVIDER_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "mock": "Mock (heuristic)",
}

_PROVIDER_KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

app = FastAPI(
    title="llm-svc",
    description="LLM analysis service — prompt building, providers, validation",
    version="0.1.0",
)
add_error_handlers(app)

validator = ReportValidator()


def _current_model() -> str:
    return os.environ.get("LLM_MODEL") or _DEFAULT_MODELS.get(
        LLM_PROVIDER, "(unknown)"
    )


@app.get("/health", tags=["Health"])
def health() -> dict:
    return health_payload(
        "llm-svc", provider=LLM_PROVIDER, model=_current_model()
    )


@app.get("/providers", tags=["Providers"])
def list_providers() -> dict:
    """List all providers with availability (whether the API key is set)."""
    items = []
    for provider_id in ("mock", "deepseek", "openai", "anthropic"):
        key_env = _PROVIDER_KEY_ENVS.get(provider_id)
        available = True
        if key_env is not None:
            available = bool(os.environ.get(key_env))
        model = os.environ.get("LLM_MODEL") or _DEFAULT_MODELS[provider_id]
        items.append(
            ProviderInfo(
                id=provider_id,  # type: ignore[arg-type]
                name=_PROVIDER_NAMES[provider_id],
                model=model,
                available=available,
            )
        )
    return {"items": [item.model_dump() for item in items]}


@app.post("/analyse", response_model=IncidentReport, tags=["Analyse"])
async def analyse_evidence(package: EvidencePackage) -> IncidentReport:
    """Analyse a redacted evidence package and return an incident report."""
    log.info(
        "analyse_started",
        namespace=package.namespace,
        pod=package.pod_name,
        provider=LLM_PROVIDER,
    )
    try:
        provider = get_provider()
        report = await provider.analyse(package)
    except Exception as e:
        log.error("analyse_failed", error=str(e), provider=LLM_PROVIDER)
        raise HTTPException(
            status_code=500, detail=f"Analysis failed: {e}"
        ) from e
    log.info(
        "analyse_complete",
        category=report.failure_category,
        severity=report.severity,
        confidence=report.confidence,
    )
    return report
