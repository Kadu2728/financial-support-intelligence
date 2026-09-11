"""Historico de consultas.

Autorizacao em dois niveis (ver auth/dependencies.py): qualquer autenticado acessa a
rota; o REGISTRO so e visivel ao dono ou a um ADMIN — e a negativa e 404, nao 403.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.dependencies import SessionDep
from app.core.errors import NotFoundError
from app.modules.auth.dependencies import CurrentUser, ensure_owner_or_admin
from app.modules.queries.repository import QueryRepository
from app.modules.queries.schemas import QueryOut, QueryPage, QuerySummary
from app.modules.users.models import Role

router = APIRouter(prefix="/queries", tags=["queries"])


@router.get("", response_model=QueryPage, summary="Historico de consultas")
async def list_queries(
    session: SessionDep,
    user: CurrentUser,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=100)] = 20,
    todos: Annotated[bool, Query(description="ADMIN: consultas de todos os usuarios")] = False,
) -> QueryPage:
    # `todos` so tem efeito para ADMIN. Para um analista e silenciosamente ignorado
    # em vez de dar 403: o parametro nao e um segredo, e o resultado e o mesmo que
    # ele veria sem o parametro.
    dono = None if (todos and user.role is Role.ADMIN) else user.id
    resultado = await QueryRepository(session).list_for_user(dono, pagina=pagina, tamanho=tamanho)
    return QueryPage(
        itens=[QuerySummary.from_query(q, feedback_de=user.id) for q in resultado.itens],
        total=resultado.total,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.get("/{query_id}", response_model=QueryOut, summary="Detalhe de uma consulta")
async def get_query(query_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> QueryOut:
    repo = QueryRepository(session)
    query = await repo.get(query_id)
    if query is None:
        raise NotFoundError("Consulta nao encontrada.")
    ensure_owner_or_admin(user, query.user_id)

    citacoes = await repo.resolve_citations(query.answer.id) if query.answer else []
    return QueryOut.from_query(query, citacoes, feedback_de=user.id)
