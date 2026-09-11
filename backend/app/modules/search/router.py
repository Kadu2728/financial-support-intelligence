"""Busca direta sobre o acervo, sem geracao.

Existe separada do copilot por dois motivos: o analista as vezes quer o trecho, nao
uma resposta redigida; e e a ferramenta de diagnostico do RAG — quando uma resposta
vem errada, a pergunta e "o retrieval trouxe o chunk certo?", e esta tela responde.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import SessionDep, SettingsDep
from app.integrations.gemini.client import GeminiClient
from app.modules.auth.dependencies import CurrentUser
from app.modules.search.repository import SearchRepository
from app.modules.search.schemas import SearchRequest, SearchResponse
from app.modules.search.service import SearchService

router = APIRouter(prefix="/search", tags=["search"])


def get_search_service(
    request: Request, settings: SettingsDep, session: SessionDep
) -> SearchService:
    # O cliente pode ser None (chave ausente): a busca lexical continua funcionando,
    # e so a perna semantica responde 503 — melhor que derrubar a tela inteira.
    gemini: GeminiClient | None = getattr(request.app.state, "gemini", None)
    return SearchService(settings=settings, repository=SearchRepository(session), embeddings=gemini)


SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]


@router.post("", response_model=SearchResponse, summary="Busca hibrida no acervo")
async def search(
    corpo: SearchRequest, service: SearchServiceDep, user: CurrentUser
) -> SearchResponse:
    resultado = await service.search(corpo.question, mode=corpo.mode, top_k=corpo.top_k)
    return SearchResponse.from_result(resultado)
