"""llm-svc — LLM analysis service.

Implements contracts/api/llm.yaml. Owns all LLM provider integrations
(mock, openai, anthropic, deepseek, openrouter), prompt building, and structured
output validation. The only service that holds external LLM API keys.

API keys can come from the environment (LLM_PROVIDER + *_API_KEY) or
from the runtime config file (written via POST /config from the
Settings page). File values take precedence over environment values.
"""

import os

import structlog
from fastapi import FastAPI, HTTPException
from k8s_llm_shared import (
    AnalysisExplanation,
    AnalysisInputSummary,
    EvidencePackage,
    IncidentReport,
    LLMConfigStatus,
    ProviderConfigRequest,
    ProviderInfo,
)
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.cache import build_cache_key, get_analysis_cache
from app.config_store import (
    DEFAULT_CONFIG_PATH,
    KEEP_MODEL,
    PROVIDER_IDS,
    PROVIDER_NAMES,
    LLMConfigStore,
    provider_model_options,
)
from app.llm import get_provider
from app.llm.errors import LLMError
from app.validator import ReportValidator

log = structlog.get_logger()


def _store() -> LLMConfigStore:
    return LLMConfigStore(os.environ.get("LLM_CONFIG_PATH", DEFAULT_CONFIG_PATH))


def _current_provider() -> str:
    provider, _, _ = _store().resolve_provider()
    return provider


def _current_model() -> str:
    provider, _, _ = _store().resolve_provider()
    return _store().resolve_model(provider)


async def _model_options(store: LLMConfigStore) -> dict[str, list[dict[str, str]]]:
    return {
        pid: await provider_model_options(pid, store.resolve_api_key(pid))
        for pid in PROVIDER_IDS
    }


app = FastAPI(
    title="llm-svc",
    description="LLM analysis service — prompt building, providers, validation",
    version="0.1.0",
)
add_error_handlers(app)

validator = ReportValidator()


def _input_summary(package: EvidencePackage) -> AnalysisInputSummary:
    evidence_text = "\n".join(
        (
            package.current_logs,
            package.previous_logs,
            package.pod_status_summary,
            package.k8s_events_filtered,
        )
    )
    return AnalysisInputSummary(
        current_log_lines=len(package.current_logs.splitlines()),
        previous_log_lines=len(package.previous_logs.splitlines()),
        has_pod_status=bool(package.pod_status_summary.strip()),
        has_kubernetes_events=bool(package.k8s_events_filtered.strip()),
        restart_count=package.restart_count,
        related_pod_count=len(package.pod_names),
        redaction_applied=True,
        redaction_count=evidence_text.count("REDACTED"),
    )


def _ensure_explanation(
    report: IncidentReport, package: EvidencePackage
) -> IncidentReport:
    """Attach deterministic provenance and safely handle older provider output."""
    explanation = report.analysis_explanation
    if explanation is None:
        explanation = AnalysisExplanation(
            rationale=report.likely_root_cause,
            key_signals=[
                f"{item.source}: {item.evidence[:160]}"
                for item in report.supporting_evidence[:5]
            ],
            uncertainty=(
                "The provider did not return a structured uncertainty statement. "
                "Review the cited evidence and complete the verification steps."
            ),
        )
        report.analysis_explanation = explanation
    elif not explanation.rationale:
        explanation.rationale = report.likely_root_cause
    if not explanation.uncertainty:
        explanation.uncertainty = (
            "Review the cited evidence and complete the human verification steps "
            "before applying remediation."
        )
    explanation.input_summary = _input_summary(package)
    return report


@app.get("/health", tags=["Health"])
def health() -> dict:
    return health_payload(
        "llm-svc", provider=_current_provider(), model=_current_model()
    )


@app.get("/providers", tags=["Providers"])
async def list_providers() -> dict:
    """List all providers with availability (whether a key is set)."""
    store = _store()
    model_options = await _model_options(store)
    items = [
        ProviderInfo(
            id=pid,  # type: ignore[arg-type]
            name=PROVIDER_NAMES[pid],
            model=store.resolve_model(pid),
            available=store.is_available(pid),
            models=model_options.get(pid, []),
        )
        for pid in PROVIDER_IDS
    ]
    return {"items": [item.model_dump() for item in items]}


@app.get("/config", response_model=LLMConfigStatus, tags=["Providers"])
async def get_config() -> LLMConfigStatus:
    """Return the active provider config — never includes key values."""
    model_options = await _model_options(_store())
    return LLMConfigStatus.model_validate(_store().get_status(model_options))


@app.post("/config", response_model=LLMConfigStatus, tags=["Providers"])
async def set_config(req: ProviderConfigRequest) -> LLMConfigStatus:
    """Set the active provider, optionally storing/clearing a key and model.

    API key values are persisted server-side and never echoed back.
    """
    model = req.model if "model" in req.model_fields_set else KEEP_MODEL
    try:
        _store().set_config(
            provider=req.provider,
            api_key=req.api_key,
            clear_key=req.clear_key,
            model=model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log.info(
        "llm_config_updated",
        provider=req.provider,
        key_updated=req.api_key is not None,
        key_cleared=req.clear_key,
        model_updated=model is not KEEP_MODEL,
    )
    model_options = await _model_options(_store())
    return LLMConfigStatus.model_validate(_store().get_status(model_options))


@app.post("/analyse", response_model=IncidentReport, tags=["Analyse"])
async def analyse_evidence(package: EvidencePackage) -> IncidentReport:
    """Analyse a redacted evidence package and return an incident report."""
    log.info(
        "analyse_started",
        namespace=package.namespace,
        pod=package.pod_name,
        provider=_current_provider(),
    )
    try:
        provider = get_provider()
        provider_name = _current_provider()
        provider_model = getattr(provider, "model", None) or _current_model()
        cache = get_analysis_cache()
        cache_key = build_cache_key(
            package, provider=provider_name, model=provider_model
        )
        report = await cache.get(cache_key)
        if report is not None:
            log.info(
                "analyse_cache_hit",
                provider=provider_name,
                model=provider_model,
            )
        else:
            report = await provider.analyse(package)
            await cache.set(cache_key, report)
        report = _ensure_explanation(report, package)
        report.provider = provider_name
        report.model = provider_model
        report.target_kind = package.target_kind
        report.target_name = package.target_name or package.pod_name
    except LLMError as e:
        log.error(
            "analyse_failed",
            error=str(e),
            provider=_current_provider(),
            error_type=e.error_type,
            status_code=e.status_code,
        )
        raise HTTPException(
            status_code=e.status_code,
            detail=f"Analysis failed: {e}",
        ) from e
    except Exception as e:
        log.error(
            "analyse_failed",
            error=str(e),
            provider=_current_provider(),
        )
        raise HTTPException(
            status_code=500, detail=f"Analysis failed: {e}"
        ) from e
    log.info(
        "analyse_complete",
        category=report.failure_category,
        severity=report.severity,
        confidence=report.confidence,
        provider=report.provider,
        model=report.model,
    )
    return report
