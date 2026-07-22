"""FastAPI helpers shared by all platform services.

This module requires FastAPI (installed by every service, not by the
shared package itself). It provides:

- RFC 7807 error handlers (contracts/README.md §4.6)
- A standard /health endpoint factory (§4.8)
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from k8s_llm_shared.errors import ProblemDetail
from k8s_llm_shared.models import HealthResponse

DEFAULT_VERSION = os.environ.get("SERVICE_VERSION", "0.1.0")


def _problem_response(problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


def add_error_handlers(app: FastAPI) -> None:
    """Register RFC 7807 handlers for HTTP, validation, and unknown errors."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        title = _default_title(exc.status_code)
        return _problem_response(
            ProblemDetail.of(
                exc.status_code, title, detail, instance=str(request.url.path)
            )
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(part) for part in first.get("loc", []))
        msg = first.get("msg", "Invalid request")
        detail = f"{loc}: {msg}" if loc else msg
        return _problem_response(
            ProblemDetail.of(
                400, "Invalid request", detail, instance=str(request.url.path)
            )
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return _problem_response(
            ProblemDetail.of(
                500,
                "Internal server error",
                str(exc),
                type_slug="internal",
                instance=str(request.url.path),
            )
        )


def _default_title(status_code: int) -> str:
    return {
        400: "Bad request",
        404: "Not found",
        409: "Conflict",
        429: "Rate limit exceeded",
        500: "Internal server error",
        502: "Upstream service error",
        503: "Service unavailable",
    }.get(status_code, "Error")


def health_payload(
    service: str,
    *,
    version: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    cluster: Optional[str] = None,
) -> dict:
    """Build the standard health response body (§4.8)."""
    return HealthResponse(
        service=service,
        version=version or DEFAULT_VERSION,
        provider=provider,
        model=model,
        cluster=cluster,
    ).model_dump(exclude_none=True)
