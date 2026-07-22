"""Simple in-memory sliding-window rate limiter.

Per-IP request counts over a 60-second window. Suitable for v1
(single gateway replica); a distributed limiter is a v2 concern.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from k8s_llm_shared import ProblemDetail
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self._limit = requests_per_minute
        self._window_seconds = 60
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        # Never rate-limit liveness probes or CORS preflight requests
        if request.url.path == "/health" or request.method == "OPTIONS":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start = now - self._window_seconds

        hits = self._hits[client_ip]
        while hits and hits[0] < window_start:
            hits.popleft()

        if len(hits) >= self._limit:
            return JSONResponse(
                status_code=429,
                content=ProblemDetail.of(
                    429,
                    "Rate limit exceeded",
                    f"Maximum {self._limit} requests per minute",
                    instance=request.url.path,
                ).model_dump(exclude_none=True),
                media_type="application/problem+json",
            )

        hits.append(now)
        return await call_next(request)
