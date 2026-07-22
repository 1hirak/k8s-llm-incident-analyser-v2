"""Unit tests for gateway proxy error handling and parse_problem."""

import json

import httpx
import pytest
from fastapi import Request
from fastapi.responses import StreamingResponse

from app.proxy import parse_problem, proxy_request, proxy_sse


def _make_request(path: str = "/api/test") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "scheme": "http",
        "client": ("127.0.0.1", 50000),
        "server": ("localhost", 8000),
    }

    async def receive():
        return {"type": "http.request", "body": b""}

    return Request(scope, receive)


class TestParseProblem:
    def test_valid_rfc7807_body(self):
        body = json.dumps({"status": 404, "title": "Not found", "detail": "missing"}).encode()
        result = parse_problem(body)
        assert result == {"status": 404, "title": "Not found", "detail": "missing"}

    def test_invalid_json_returns_none(self):
        result = parse_problem(b"not valid json")
        assert result is None

    def test_missing_status_returns_none(self):
        body = json.dumps({"title": "error"}).encode()
        result = parse_problem(body)
        assert result is None

    def test_missing_title_returns_none(self):
        body = json.dumps({"status": 500}).encode()
        result = parse_problem(body)
        assert result is None

    def test_not_a_dict_returns_none(self):
        body = json.dumps(["a", "list"]).encode()
        result = parse_problem(body)
        assert result is None

    def test_unicode_decode_error_returns_none(self):
        result = parse_problem(b"\xff\xfe")
        assert result is None

    def test_empty_body(self):
        result = parse_problem(b"")
        assert result is None


class TestProxyRequestErrors:
    def _make_client(self, handler):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def test_http_error_returns_502(self):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        async with self._make_client(handler) as client:
            resp = await proxy_request(
                _make_request(), client, "http://collector:8002", "/collect"
            )
        assert resp.status_code == 502
        body = json.loads(resp.body)
        assert body["status"] == 502
        assert "unreachable" in body["detail"]

    async def test_successful_proxy_passthrough(self):
        def handler(request):
            return httpx.Response(
                200, json={"status": "ok"}, headers={"content-type": "application/json"}
            )

        async with self._make_client(handler) as client:
            resp = await proxy_request(
                _make_request(), client, "http://reports:8005", "/stats"
            )
        assert resp.status_code == 200
        assert json.loads(resp.body) == {"status": "ok"}

    async def test_upstream_error_passthrough(self):
        def handler(request):
            return httpx.Response(
                500,
                json={"detail": "internal error"},
                headers={"content-type": "application/json"},
            )

        async with self._make_client(handler) as client:
            resp = await proxy_request(
                _make_request(), client, "http://collector:8002", "/collect"
            )
        assert resp.status_code == 500
        assert json.loads(resp.body) == {"detail": "internal error"}


class TestProxySSEErrors:
    async def test_sse_connect_error_returns_502(self):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        resp = await proxy_sse(
            _make_request("/api/jobs/abc/stream"),
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            "http://orchestrator:8001",
            "/jobs/abc/stream",
        )
        assert resp.status_code == 502
        body = json.loads(resp.body)
        assert body["status"] == 502
        assert "Upstream unreachable" in body["detail"]
