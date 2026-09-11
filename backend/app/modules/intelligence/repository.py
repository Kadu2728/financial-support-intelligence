"""Agregacoes do Support Intelligence.

Regra unica: **nenhum numero e inventado.** Tudo aqui e SELECT sobre `queries`,
`answers`, `citations` e `feedback`. Onde a amostra e pequena demais para uma taxa
significar alguma coisa, a taxa vai como `None` e a tela diz "amostra insuficiente"
— em vez de mostrar 100% de sucesso sobre duas consultas.

As consultas sao restritas a uma janela (`desde`) para que o custo nao cresca com o
historico inteiro; os indices `ix_queries_created` e `ix_queries_gaps` cobrem os
filtros.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document, DocumentChunk, DocumentVersion
from app.modules.feedback.models import Feedback, FeedbackRating
from app.modules.queries.models import Answer, Citation, Query, QueryStatus


@dataclass(frozen=True, slots=True)
class Totais:
    consultas: int
    sucesso: int
    sem_evidencia: int
    falhas: int


@dataclass(frozen=True, slots=True)
class Latencia:
    p50_ms: int | None
    p95_ms: int | None
    media_ms: int | None
    retrieval_medio_ms: int | None
    generation_medio_ms: int | None


@dataclass(frozen=True, slots=True)
class DiaSerie:
    dia: date
    consultas: int
    sem_evidencia: int


@dataclass(frozen=True, slots=True)
class DocumentoCitado:
    document_id: uuid.UUID
    title: str
    citacoes: int
    consultas: int


@dataclass(frozen=True, slots=True)
class SecaoCitada:
    document_id: uuid.UUID
    document_title: str
    section_path: str | None
    citacoes: int


@dataclass(frozen=True, slots=True)
class ResumoFeedback:
    total: int
    positivos: int
    negativos: int
    motivos: list[tuple[str, int]]


@dataclass(frozen=True, slots=True)
class Lacuna:
    query_id: uuid.UUID
    question: str
    created_at: datetime
    top_score: float | None
    embedding: list[float] | None


class IntelligenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def totais(self, desde: datetime) -> Totais:
        resultado = await self._session.execute(
            select(Query.status, func.count())
            .where(Query.created_at >= desde)
            .group_by(Query.status)
        )
        por_status = {linha[0]: int(linha[1]) for linha in resultado.all()}
        return Totais(
            consultas=sum(por_status.values()),
            sucesso=por_status.get(QueryStatus.SUCCESS, 0),
            sem_evidencia=por_status.get(QueryStatus.INSUFFICIENT_EVIDENCE, 0),
            falhas=por_status.get(QueryStatus.FAILED, 0),
        )

    async def latencia(self, desde: datetime) -> Latencia:
        """Percentis calculados pelo Postgres (`percentile_cont`), nao em Python.

        Trazer todas as latencias para calcular p95 na aplicacao escalaria com o
        volume de consultas; a agregacao no banco escala com o indice.
        """
        p50 = func.percentile_cont(0.5).within_group(Query.total_ms)
        p95 = func.percentile_cont(0.95).within_group(Query.total_ms)
        linha = (
            await self._session.execute(
                select(
                    p50,
                    p95,
                    func.avg(Query.total_ms),
                    func.avg(Query.retrieval_ms),
                    func.avg(Query.generation_ms),
                ).where(Query.created_at >= desde, Query.total_ms.is_not(None))
            )
        ).one()
        return Latencia(
            p50_ms=_inteiro(linha[0]),
            p95_ms=_inteiro(linha[1]),
            media_ms=_inteiro(linha[2]),
            retrieval_medio_ms=_inteiro(linha[3]),
            generation_medio_ms=_inteiro(linha[4]),
        )

    async def confianca_media(self, desde: datetime) -> float | None:
        valor = await self._session.scalar(
            select(func.avg(Query.confidence)).where(
                Query.created_at >= desde, Query.status == QueryStatus.SUCCESS
            )
        )
        return round(float(valor), 3) if valor is not None else None

    async def serie_diaria(self, desde: datetime) -> list[DiaSerie]:
        dia = func.date_trunc("day", Query.created_at).label("dia")
        sem_evidencia = func.count().filter(Query.status == QueryStatus.INSUFFICIENT_EVIDENCE)
        resultado = await self._session.execute(
            select(dia, func.count(), sem_evidencia)
            .where(Query.created_at >= desde)
            .group_by(dia)
            .order_by(dia)
        )
        return [
            DiaSerie(dia=linha[0].date(), consultas=int(linha[1]), sem_evidencia=int(linha[2]))
            for linha in resultado.all()
        ]

    async def documentos_mais_citados(
        self, desde: datetime, *, limite: int
    ) -> list[DocumentoCitado]:
        resultado = await self._session.execute(
            select(
                Document.id,
                Document.title,
                func.count(Citation.id),
                func.count(func.distinct(Answer.query_id)),
            )
            .join(DocumentVersion, DocumentVersion.id == Citation.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .join(Answer, Answer.id == Citation.answer_id)
            .where(Citation.created_at >= desde)
            .group_by(Document.id, Document.title)
            .order_by(func.count(Citation.id).desc(), Document.title)
            .limit(limite)
        )
        return [
            DocumentoCitado(
                document_id=linha[0],
                title=linha[1],
                citacoes=int(linha[2]),
                consultas=int(linha[3]),
            )
            for linha in resultado.all()
        ]

    async def secoes_mais_citadas(self, desde: datetime, *, limite: int) -> list[SecaoCitada]:
        resultado = await self._session.execute(
            select(Document.id, Document.title, DocumentChunk.section_path, func.count(Citation.id))
            .join(DocumentChunk, DocumentChunk.id == Citation.document_chunk_id)
            .join(DocumentVersion, DocumentVersion.id == Citation.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Citation.created_at >= desde)
            .group_by(Document.id, Document.title, DocumentChunk.section_path)
            .order_by(func.count(Citation.id).desc(), Document.title)
            .limit(limite)
        )
        return [
            SecaoCitada(
                document_id=linha[0],
                document_title=linha[1],
                section_path=linha[2],
                citacoes=int(linha[3]),
            )
            for linha in resultado.all()
        ]

    async def feedback(self, desde: datetime) -> ResumoFeedback:
        por_rating = (
            await self._session.execute(
                select(Feedback.rating, func.count())
                .where(Feedback.created_at >= desde)
                .group_by(Feedback.rating)
            )
        ).all()
        contagem = {linha[0]: int(linha[1]) for linha in por_rating}

        motivos = (
            await self._session.execute(
                select(Feedback.reason, func.count())
                .where(
                    Feedback.created_at >= desde,
                    Feedback.rating == FeedbackRating.NEGATIVE,
                    Feedback.reason.is_not(None),
                )
                .group_by(Feedback.reason)
                .order_by(func.count().desc())
            )
        ).all()
        return ResumoFeedback(
            total=sum(contagem.values()),
            positivos=contagem.get(FeedbackRating.POSITIVE, 0),
            negativos=contagem.get(FeedbackRating.NEGATIVE, 0),
            motivos=[(str(linha[0].value), int(linha[1])) for linha in motivos],
        )

    async def lacunas(self, desde: datetime, *, limite: int) -> list[Lacuna]:
        """Perguntas que o acervo nao respondeu, mais recentes primeiro.

        Traz o embedding para o agrupamento por semelhanca no service — ja
        calculado na hora da consulta, sem nenhuma chamada extra ao Gemini.
        """
        resultado = await self._session.execute(
            select(Query.id, Query.question, Query.created_at, Query.top_score, Query.embedding)
            .where(
                Query.created_at >= desde,
                Query.status == QueryStatus.INSUFFICIENT_EVIDENCE,
            )
            .order_by(Query.created_at.desc())
            .limit(limite)
        )
        return [
            Lacuna(
                query_id=linha[0],
                question=linha[1],
                created_at=linha[2],
                top_score=linha[3],
                embedding=list(linha[4]) if linha[4] is not None else None,
            )
            for linha in resultado.all()
        ]

    async def acervo(self) -> tuple[int, int]:
        """Documentos ativos e chunks indexados: o tamanho do que o copilot enxerga."""
        docs = await self._session.scalar(
            select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
        )
        chunks = await self._session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .where(DocumentVersion.is_current.is_(True))
        )
        return int(docs or 0), int(chunks or 0)


def _inteiro(valor: object) -> int | None:
    if valor is None:
        return None
    return round(float(str(valor)))
