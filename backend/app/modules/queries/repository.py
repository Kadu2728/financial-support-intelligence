from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.documents.models import Document, DocumentChunk, DocumentVersion
from app.modules.queries.models import Answer, Citation, Query, QueryStatus


@dataclass(frozen=True, slots=True)
class CitacaoResolvida:
    """Citacao com o que a tela precisa para exibi-la e abrir a fonte."""

    citation: Citation
    chunk: DocumentChunk
    document_id: uuid.UUID
    document_title: str
    version_number: int


@dataclass(frozen=True, slots=True)
class PaginaConsultas:
    itens: Sequence[Query]
    total: int


class QueryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, query: Query) -> Query:
        self._session.add(query)
        await self._session.flush()
        return query

    async def get(self, query_id: uuid.UUID) -> Query | None:
        """Consulta com resposta, citacoes e feedback carregados.

        `selectinload` explicito porque todo relationship usa `lazy="raise"`.
        """
        resultado = await self._session.execute(
            select(Query)
            .where(Query.id == query_id)
            .options(
                selectinload(Query.answer).selectinload(Answer.citations),
                selectinload(Query.feedback),
            )
        )
        return resultado.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID | None, *, pagina: int, tamanho: int
    ) -> PaginaConsultas:
        """Historico. `user_id=None` lista de todos — reservado ao ADMIN pelo router."""
        consulta = select(Query)
        if user_id is not None:
            consulta = consulta.where(Query.user_id == user_id)

        total = await self._session.scalar(select(func.count()).select_from(consulta.subquery()))
        resultado = await self._session.execute(
            consulta.options(selectinload(Query.answer), selectinload(Query.feedback))
            .order_by(Query.created_at.desc())
            .offset((pagina - 1) * tamanho)
            .limit(tamanho)
        )
        return PaginaConsultas(itens=list(resultado.scalars().all()), total=total or 0)

    async def resolve_citations(self, answer_id: uuid.UUID) -> list[CitacaoResolvida]:
        """Citacoes com chunk e documento, na ordem do rank.

        Um JOIN em vez de N buscas: a tela de resposta exibe todas de uma vez.
        """
        resultado = await self._session.execute(
            select(
                Citation,
                DocumentChunk,
                Document.id,
                Document.title,
                DocumentVersion.version_number,
            )
            .join(DocumentChunk, DocumentChunk.id == Citation.document_chunk_id)
            .join(DocumentVersion, DocumentVersion.id == Citation.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Citation.answer_id == answer_id)
            .order_by(Citation.rank)
        )
        return [
            CitacaoResolvida(
                citation=linha[0],
                chunk=linha[1],
                document_id=linha[2],
                document_title=linha[3],
                version_number=linha[4],
            )
            for linha in resultado.all()
        ]

    async def count_by_status(self, user_id: uuid.UUID) -> dict[QueryStatus, int]:
        resultado = await self._session.execute(
            select(Query.status, func.count())
            .where(Query.user_id == user_id)
            .group_by(Query.status)
        )
        return {linha[0]: int(linha[1]) for linha in resultado.all()}
