"""Middlewares de infraestrutura.

O `request_id` e a espinha da observabilidade: gerado (ou aceito do header) na borda, injetado
no contexto do structlog, propagado para todo log emitido durante a requisicao e devolvido ao
cliente. Um usuario que reporta um erro traz o identificador, e ele leva ao rastro completo.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Ruido operacional: health checks de plataforma batem a cada poucos segundos.
_SILENT_PATHS = frozenset({"/health", "/health/ready", "/favicon.ico"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Atribui request_id, mede a latencia e registra o resultado."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Aceita o id de um proxy upstream para manter a correlacao ponta a ponta,
        # mas trunca: e entrada externa e vai para dentro de todo log.
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming[:64] if incoming else uuid.uuid4().hex

        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # O handler global monta a resposta; aqui so garantimos que a latencia de uma
            # requisicao que explodiu tambem seja registrada.
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["Server-Timing"] = f"app;dur={duration_ms}"

        if request.url.path not in _SILENT_PATHS:
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Headers de seguranca aplicados a toda resposta.

    A API responde JSON, entao CSP aqui e minima — a CSP que importa e a do Next, que serve
    HTML. Estes headers protegem contra sniffing de tipo e embedding indevido das respostas.
    """

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
