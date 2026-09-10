"""Contexte de requête : correlation_id, log HTTP d'accès."""

import time
from uuid import uuid4

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

CORRELATION_ID_HEADER = "X-Correlation-ID"

logger = get_logger(__name__)


def get_correlation_id(request: Request) -> str | None:
    """Correlation id de la requête, si le middleware l'a posé."""
    state = request.scope.get("state")
    if not isinstance(state, dict):
        return None
    value = state.get("correlation_id")
    return value if isinstance(value, str) else None


class RequestContextMiddleware:
    """Middleware ASGI : attache un correlation_id à la requête et aux logs.

    Middleware ASGI pur (et non ``BaseHTTPMiddleware``) afin que le contexte
    reste visible depuis le handler d'exception global, situé plus à l'extérieur
    dans la pile Starlette.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(CORRELATION_ID_HEADER)
        correlation_id = incoming or uuid4().hex

        state = scope.setdefault("state", {})
        state["correlation_id"] = correlation_id

        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        status_code = 500
        started = time.perf_counter()

        async def send_with_correlation_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append(CORRELATION_ID_HEADER, correlation_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation_id)
        finally:
            logger.info(
                "http_request",
                method=scope.get("method"),
                path=scope.get("path"),
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.unbind_contextvars("correlation_id")
