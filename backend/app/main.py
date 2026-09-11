"""Entrypoint da aplicacao.

Responsabilidade unica: montar a aplicacao. Nenhuma regra de negocio vive aqui — cada
modulo registra seu proprio router e o `main` apenas os agrega.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.dependencies import SessionDep
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.db.session import create_engine, create_session_factory
from app.modules.auth.router import router as auth_router
from app.modules.documents.router import get_storage
from app.modules.documents.router import router as documents_router
from app.modules.feedback.router import router as feedback_router
from app.modules.ingestion.worker import IngestionWorker
from app.modules.intelligence.router import router as intelligence_router
from app.modules.queries.router import router as queries_router
from app.modules.rag.router import router as copilot_router
from app.modules.search.router import router as search_router
from app.modules.users.router import router as users_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Abre e fecha os recursos de longa duracao.

    O engine e criado aqui e nao no import: um pool de conexoes criado em tempo de
    import vaza para processos filhos de worker e para a coleta de testes.
    """
    settings: Settings = app.state.settings

    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    # Cliente do Gemini compartilhado pelo worker e pelo copilot: um pool HTTP so.
    # `None` quando a chave nao esta configurada — os endpoints que dependem dele
    # respondem 503 com a causa, em vez de a aplicacao recusar-se a subir.
    app.state.gemini = None
    if settings.gemini_configured:
        from app.integrations.gemini.client import GeminiClient

        app.state.gemini = GeminiClient(settings)
    else:
        logger.warning("gemini_not_configured", hint="defina GEMINI_API_KEY no .env")

    parar_worker = asyncio.Event()
    tarefa_worker: asyncio.Task[None] | None = None
    if settings.worker_enabled and app.state.gemini is not None:
        worker = IngestionWorker(
            settings=settings,
            session_factory=app.state.session_factory,
            storage=get_storage(settings),
            embeddings=app.state.gemini,
        )
        tarefa_worker = asyncio.create_task(worker.run_forever(parar_worker), name="ingestion")
    elif settings.worker_enabled:
        logger.warning("worker_disabled", reason="gemini_not_configured")

    logger.info("application_startup", env=settings.app_env.value, version=app.version)
    try:
        yield
    finally:
        if tarefa_worker is not None:
            # Sinaliza e espera: um job no meio da gravacao termina a transacao em
            # vez de ser cancelado com o banco em estado indefinido.
            parar_worker.set()
            with suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(tarefa_worker, timeout=30)
        if app.state.gemini is not None:
            await app.state.gemini.aclose()
        # Sem o dispose, as conexoes ficam abertas do lado do Neon ate expirarem —
        # e o plano gratuito tem um limite baixo de conexoes simultaneas.
        await engine.dispose()
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
    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(users_router, prefix=settings.api_v1_prefix)
    app.include_router(documents_router, prefix=settings.api_v1_prefix)
    app.include_router(search_router, prefix=settings.api_v1_prefix)
    app.include_router(copilot_router, prefix=settings.api_v1_prefix)
    app.include_router(queries_router, prefix=settings.api_v1_prefix)
    app.include_router(feedback_router, prefix=settings.api_v1_prefix)
    app.include_router(intelligence_router, prefix=settings.api_v1_prefix)

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
async def health_ready(session: SessionDep, response: Response) -> dict[str, object]:
    """Verifica o banco antes de declarar a instancia apta a receber trafego.

    Responde 503 quando o banco esta fora: a plataforma tira a instancia do balanceador
    em vez de encaminhar requisicoes que falhariam.
    """
    checks: dict[str, str] = {}
    healthy = True

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        healthy = False
        checks["database"] = "unavailable"
        # A mensagem da excecao pode conter a connection string com a senha.
        logger.error("readiness_database_failed", error_type=type(exc).__name__)

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ready" if healthy else "degraded", "checks": checks}


app = create_app()
