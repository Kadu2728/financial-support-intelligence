"""Entrypoint da aplicacao.

Responsabilidade unica: montar a aplicacao. Nenhuma regra de negocio vive aqui — cada modulo
registra seu proprio router e o `main` apenas os agrega.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ciclo de vida. Recursos de longa duracao (pool de banco na Fase 2, worker de
    ingestao na Fase 5) sao abertos aqui e fechados na saida."""
    settings: Settings = app.state.settings
    logger.info("application_startup", env=settings.app_env.value, version=app.version)
    yield
    logger.info("application_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory.

    Receber `settings` permite que os testes montem a app com configuracao propria, sem
    variavel de ambiente global e sem estado compartilhado entre casos de teste.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        summary="Inteligencia operacional sobre documentos internos de suporte.",
        lifespan=lifespan,
        docs_url=settings.docs_url,
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings

    # Ordem importa: middleware registrado por ultimo executa primeiro. RequestContext
    # precisa envolver todo o resto para que qualquer log carregue o request_id.
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # BFF usa Bearer, nao cookie cross-site (ADR-0003)
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(health_router)

    # Fase 3+: app.include_router(auth.router, prefix=settings.api_v1_prefix)

    return app


# ---------------------------------------------------------------------------
# Health checks
#
# Dois endpoints com proposito distinto:
#   /health       liveness  — o processo esta vivo? Nunca toca dependencia externa.
#   /health/ready readiness — pode receber trafego? Verifica dependencias.
#
# Confundir os dois causa restart em loop: se o liveness verificar o banco e o banco
# oscilar, o orquestrador mata um processo saudavel e piora a indisponibilidade.
# ---------------------------------------------------------------------------
health_router = APIRouter(tags=["health"])


@health_router.get("/health", summary="Liveness")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/health/ready", summary="Readiness")
async def health_ready() -> dict[str, object]:
    # Fase 2: adicionar checagem do banco (SELECT 1) e retornar 503 se indisponivel.
    return {"status": "ready", "checks": {}}


app = create_app()
