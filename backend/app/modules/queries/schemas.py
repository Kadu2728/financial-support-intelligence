"""Formas de resposta compartilhadas por /copilot/query, /queries e /queries/{id}.

Uma consulta recem-respondida e uma consulta do historico tem a MESMA forma: o
frontend renderiza as duas com o mesmo componente. Ter dois schemas quase iguais e
o tipo de duplicacao que diverge em silencio.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.feedback.models import FeedbackRating, FeedbackReason
from app.modules.queries.models import Query, QueryStatus
from app.modules.queries.repository import CitacaoResolvida


class CitationOut(BaseModel):
    """Uma fonte da resposta, com o necessario para exibir e abrir o trecho."""

    id: str = Field(description="Identificador usado no texto da resposta: C1, C2...")
    rank: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    version_id: uuid.UUID
    version_number: int | None
    section_path: str | None
    section_label: str | None
    page_number: int | None
    excerpt: str
    char_start: int
    char_end: int
    score: float


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rating: FeedbackRating
    reason: FeedbackReason | None
    comment: str | None
    created_at: datetime


class QueryOut(BaseModel):
    id: uuid.UUID
    question: str
    status: QueryStatus
    answer: str | None
    insufficient_evidence: bool
    citations: list[CitationOut]
    # Calculada pelo sistema, nunca auto-reportada pelo modelo (ADR-0008).
    confidence: float | None
    chunks_retrieved: int
    top_score: float | None
    retrieval_ms: int | None
    generation_ms: int | None
    total_ms: int | None
    model: str | None
    error_code: str | None
    created_at: datetime
    feedback: FeedbackOut | None = None

    @classmethod
    def from_query(
        cls,
        query: Query,
        citacoes: list[CitacaoResolvida],
        *,
        feedback_de: uuid.UUID | None = None,
    ) -> QueryOut:
        resposta = query.answer
        proprio = None
        if feedback_de is not None:
            proprio = next((f for f in query.feedback if f.user_id == feedback_de), None)

        return cls(
            id=query.id,
            question=query.question,
            status=query.status,
            answer=resposta.content if resposta else None,
            insufficient_evidence=resposta.insufficient_evidence if resposta else False,
            citations=[
                CitationOut(
                    id=f"C{c.citation.rank + 1}",
                    rank=c.citation.rank,
                    chunk_id=c.chunk.id,
                    document_id=c.document_id,
                    document_title=c.document_title,
                    version_id=c.citation.document_version_id,
                    version_number=c.version_number,
                    section_path=c.chunk.section_path,
                    section_label=c.chunk.section_label,
                    page_number=c.chunk.page_number,
                    excerpt=c.chunk.content,
                    char_start=c.chunk.char_start,
                    char_end=c.chunk.char_end,
                    score=c.citation.score,
                )
                for c in citacoes
            ],
            confidence=query.confidence,
            chunks_retrieved=query.chunks_retrieved,
            top_score=query.top_score,
            retrieval_ms=query.retrieval_ms,
            generation_ms=query.generation_ms,
            total_ms=query.total_ms,
            model=query.model,
            error_code=query.error_code,
            created_at=query.created_at,
            feedback=FeedbackOut.model_validate(proprio) if proprio else None,
        )


class QuerySummary(BaseModel):
    """Linha do historico: sem citacoes nem texto completo."""

    id: uuid.UUID
    question: str
    status: QueryStatus
    answer_preview: str | None
    confidence: float | None
    total_ms: int | None
    created_at: datetime
    feedback_rating: FeedbackRating | None

    @classmethod
    def from_query(cls, query: Query, *, feedback_de: uuid.UUID | None) -> QuerySummary:
        resposta = query.answer
        proprio = None
        if feedback_de is not None:
            proprio = next((f for f in query.feedback if f.user_id == feedback_de), None)
        conteudo = resposta.content if resposta else None
        return cls(
            id=query.id,
            question=query.question,
            status=query.status,
            answer_preview=(conteudo[:200] + "…") if conteudo and len(conteudo) > 200 else conteudo,
            confidence=query.confidence,
            total_ms=query.total_ms,
            created_at=query.created_at,
            feedback_rating=proprio.rating if proprio else None,
        )


class QueryPage(BaseModel):
    itens: list[QuerySummary]
    total: int
    pagina: int
    tamanho: int
