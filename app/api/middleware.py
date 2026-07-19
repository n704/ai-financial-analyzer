"""Cross-cutting HTTP middleware (P1.13): request-context JSON logging and
per-IP + per-user rate limiting via the ``Cache`` interface.

Order matters: ``app/main.py`` adds ``RateLimitMiddleware`` first and
``RequestContextMiddleware`` last, so the context middleware ends up
*outermost* (Starlette runs the most-recently-added middleware first) — every
log line, including a 429 from the rate limiter, carries the request id.
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.auth.security import decode_access_token
from app.api.state import AppState

log = structlog.get_logger()

_AUTH_PREFIX = "/api/v1/auth"
_BEARER_PREFIX = "bearer "


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Binds a request id (+ method/path) to structlog's contextvars for the
    duration of the request, and emits one JSON access-log line per request.
    Document/request *content* is never logged — only metadata."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        structlog.contextvars.clear_contextvars()
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=request.method, path=request.url.path
        )
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "http.request_failed",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            raise
        response.headers["X-Request-ID"] = request_id
        log.info(
            "http.request",
            status_code=response.status_code,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP fixed-window limiting (stricter on auth endpoints, per SPEC.md
    §3.1), plus a per-user limit when the request carries a well-formed bearer
    token. Backed by ``Cache.incr`` — in-memory by default, Redis when scaled,
    with identical behavior either way (ARCHITECTURE.md §6)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        state: AppState = request.app.state.app_state
        cache = state.infra.cache
        limits = state.settings.rate_limit
        is_auth_path = request.url.path.startswith(_AUTH_PREFIX)

        client_ip = request.client.host if request.client else "unknown"
        ip_bucket = "auth" if is_auth_path else "all"
        ip_limit = limits.auth_per_ip_per_minute if is_auth_path else limits.per_ip_per_minute
        ip_count = await cache.incr(f"ratelimit:ip:{ip_bucket}:{client_ip}", ttl_s=60)
        if ip_count > ip_limit:
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)

        user_id = _peek_user_id(request, state)
        if user_id is not None:
            user_count = await cache.incr(f"ratelimit:user:{user_id}", ttl_s=60)
            if user_count > limits.per_user_per_minute:
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)

        return await call_next(request)


def _peek_user_id(request: Request, state: AppState) -> str | None:
    """Best-effort decode of a bearer token purely to bucket the per-user rate
    limit — never trusted for authorization. An invalid/expired token just
    means no per-user bucketing here; the route's own ``get_current_user``
    dependency is what actually rejects it. Avoids a DB round trip on every
    request just to rate-limit."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith(_BEARER_PREFIX):
        return None
    token = auth_header[len(_BEARER_PREFIX) :]
    try:
        secret = state.settings.auth.resolve_secret().get_secret_value()
        return decode_access_token(
            token, secret=secret, algorithm=state.settings.auth.jwt_algorithm
        )
    except Exception:
        return None
