"""processor-svc — evidence preprocessing and redaction service.

Implements contracts/api/processor.yaml. Combines two pipeline stages:
preprocessing (noise/signal filtering) and redaction (secret masking).
Pure CPU service — no database, no Redis, no external API calls.
"""

import os

import structlog
from fastapi import FastAPI, HTTPException
from k8s_llm_shared import EvidencePackage, RawEvidence
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.preprocessor import LogPreprocessor
from app.redactor import LogRedactor

log = structlog.get_logger()

MAX_LOG_LINES = int(os.environ.get("MAX_LOG_LINES", "100"))
CONTEXT_WINDOW = int(os.environ.get("CONTEXT_WINDOW", "3"))

app = FastAPI(
    title="processor-svc",
    description="Evidence preprocessing and redaction service",
    version="0.1.0",
)
add_error_handlers(app)

preprocessor = LogPreprocessor(
    max_log_lines=MAX_LOG_LINES, context_window=CONTEXT_WINDOW
)
redactor = LogRedactor()


@app.get("/health", tags=["Health"])
def health() -> dict:
    return health_payload("processor-svc")


@app.post("/process", response_model=EvidencePackage, tags=["Process"])
def process_evidence(evidence: RawEvidence) -> EvidencePackage:
    """Preprocess and redact raw evidence from the collector."""
    log.info(
        "process_started", namespace=evidence.namespace, pod=evidence.pod_name
    )
    try:
        filtered = preprocessor.process(evidence)
        safe = redactor.redact(filtered)
    except Exception as e:
        log.error("process_failed", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Processing failed: {e}"
        ) from e
    log.info(
        "process_complete",
        namespace=safe.namespace,
        pod=safe.pod_name,
        log_lines=len(safe.current_logs.splitlines()),
    )
    return safe
