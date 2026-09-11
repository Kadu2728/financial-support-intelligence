from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.dependencies import SessionDep, SettingsDep
from app.core.ratelimit import SlidingWindowLimiter
from app.integrations.gemini.client import GeminiClient
from app.modules.auth.dependencies import CurrentUser
from app.modules.queries.repository import QueryRepository
from app.modules.queries.schemas import QueryOut
from app.modules.rag.service import RagService
from app.modules.search.repository import SearchRepository
from app.modules.search.service import SearchService

router = APIRouter(prefix="/copilot", tags=["copilot"])


class CopilotRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def get_rag_service(request: Request, settings: SettingsDep, session: SessionDep) -> RagService:
    gemini: GeminiClient | None = getattr(request.app.state, "gemini", None)
    return RagService(
        settings=settings,
        search=SearchService(
            settings=settings, repository=SearchRepository(session), embeddings=gemini
        ),
        generation=gemini,
        queries=QueryRepository(session),
        session=session,
    )


def get_copilot_limiter(request: Request, settings: SettingsDep) -> SlidingWindowLimiter:
    """Um limiter por processo, criado sob demanda e guardado em `app.state`."""
    limiter: SlidingWindowLimiter | None = getattr(request.app.state, "copilot_limiter", None)
    if limiter is None:
        limiter = SlidingWindowLimiter(max_per_window=settings.rate_limit_copilot_per_minute)
        request.app.state.copilot_limiter = limiter
    return limiter


RagServiceDep = Annotated[RagService, Depends(get_rag_service)]
LimiterDep = Annotated[SlidingWindowLimiter, Depends(get_copilot_limiter)]


@router.post(
    "/query",
    response_model=QueryOut,
    summary="Pergunta ao copilot",
    responses={
        429: {"description": "Limite de perguntas por minuto"},
        502: {"description": "Falha na geracao"},
        503: {"description": "GEMINI_API_KEY nao configurada"},
    },
)
async def ask(
    corpo: CopilotRequest,
    service: RagServiceDep,
    limiter: LimiterDep,
    user: CurrentUser,
    session: SessionDep,
) -> QueryOut:
    """Responde com base no acervo, ou recusa explicitamente.

    A resposta tem a MESMA forma de `GET /queries/{id}`: o frontend usa um so
    componente para resposta recem-gerada e para historico.
    """
    limiter.check(str(user.id))
    resposta = await service.answer(corpo.question, user_id=user.id)

    # O flush ja aconteceu; o commit e da borda (get_db). Recarregar com as citacoes
    # resolvidas garante que a resposta sai exatamente como o historico a vera.
    repo = QueryRepository(session)
    query = await repo.get(resposta.query_id)
    assert query is not None  # acabou de ser criada nesta transacao
    citacoes = await repo.resolve_citations(query.answer.id) if query.answer else []
    return QueryOut.from_query(query, citacoes, feedback_de=user.id)
