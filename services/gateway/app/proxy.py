"""Reverse-proxy helpers for the gateway.

Forwards requests to internal services and translates failures into
RFC 7807 Problem Details (contracts/README.md §4.6). Upstream services
already emit problem+json for their own errors — those bodies are passed
through unchanged.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from k8s_llm_shared import ProblemDetail

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}


def _problem(status: int, title: str, detail: str, instance: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ProblemDetail.of(
            status, title, detail, instance=instance
        ).model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


async def proxy_request(
    request: Request,
    http: httpx.AsyncClient,
    base_url: str,
    path: str,
) -> Response:
    """Forward a non-streaming request to an internal service."""
    url = f"{base_url}{path}"
    body = await request.body()
    try:
        upstream = await http.request(
            request.method,
            url,
            params=dict(request.query_params),
            content=body if body else None,
            headers={"content-type": request.headers.get("content-type", "application/json")},
            timeout=60,
        )
    except httpx.TimeoutException:
        return _problem(
            502, "Upstream service error",
            f"Upstream timed out for {url}", request.url.path,
        )
    except httpx.HTTPError as e:
        return _problem(
            502, "Upstream service error",
            f"Upstream unreachable: {e}", request.url.path,
        )

    content_type = upstream.headers.get("content-type", "application/json")
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=content_type.split(";")[0],
    )


async def proxy_sse(
    request: Request,
    http: httpx.AsyncClient,
    base_url: str,
    path: str,
    client_factory=None,
) -> Response:
    """Open a streaming SSE proxy to an internal service.

    The upstream connection stays open for the life of the downstream
    client connection; bytes are forwarded as they arrive. A dedicated
    client with no read timeout is used so long-lived streams are not
    killed by the shared client's timeout.
    """
    url = f"{base_url}{path}"
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=None))
    client = factory()

    try:
        upstream = client.stream(
            "GET", url, params=dict(request.query_params)
        )
        upstream_resp = await upstream.__aenter__()
    except httpx.HTTPError as e:
        await client.aclose()
        return _problem(
            502, "Upstream service error",
            f"Upstream unreachable: {e}", request.url.path,
        )

    if upstream_resp.status_code != 200:
        body = await upstream_resp.aread()
        await upstream.__aexit__(None, None, None)
        await client.aclose()
        content_type = upstream_resp.headers.get("content-type", "application/json")
        return Response(
            content=body,
            status_code=upstream_resp.status_code,
            media_type=content_type.split(";")[0],
        )

    async def byte_stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream_resp.aiter_bytes():
                yield chunk
        finally:
            await upstream.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(
        byte_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def parse_problem(body: bytes) -> Optional[dict]:
    """Best-effort parse of an upstream RFC 7807 body."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(data, dict) and "status" in data and "title" in data:
        return data
    return None
