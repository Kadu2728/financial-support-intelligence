"""Consultas, respostas e citacoes.

`Query` e a tabela quente do modulo Intelligence: e varrida constantemente para
contagens, latencias e tendencias, e nunca precisa do texto da resposta. Por isso
`Answer` e uma tabela separada, apesar do 1:1 — separacao por padrao de acesso, nao por
dogma de normalizacao (docs/data-model.md).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import EMBEDDING_DIM, Base, CreatedAtMixin, uuid_pk

if TYPE_CHECKING:
    from app.modules.documents.models import DocumentChunk
    from app.modules.feedback.models import Feedback
    from app.modules.users.models import User


class QueryStatus(StrEnum):
    SUCCESS = "SUCCESS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    FAILED = "FAILED"


query_status_enum = Enum(
    QueryStatus,
    name="query_status",
    values_callable=lambda enum: [member.value for member in enum],
)


class Query(Base, CreatedAtMixin):
    __tablename__ = "queries"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QueryStatus] = mapped_column(query_status_enum, nullable=False)

    # Ja calculado para a busca — guardar custa apenas o espaco e habilita o
    # agrupamento de perguntas semelhantes no Intelligence sem nenhuma chamada extra
    # ao Gemini (docs/architecture.md §8).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    chunks_retrieved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    retrieval_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Qual modelo respondeu: sem isso, comparar qualidade ao longo do tempo e impossivel
    # depois de uma troca de modelo.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(lazy="raise")
    answer: Mapped[Answer | None] = relationship(
        back_populates="query",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )
    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="query",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_queries_user_created", "user_id", text("created_at DESC")),
        Index("ix_queries_created", text("created_at DESC")),
        # Indicador mais valioso do produto: o que o acervo nao responde.
        Index(
            "ix_queries_gaps",
            "created_at",
            postgresql_where=text("status <> 'SUCCESS'"),
        ),
        CheckConstraint("chunks_retrieved >= 0", name="chunks_retrieved_non_negative"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<Query {self.status.value} {self.question[:40]!r}>"


class Answer(Base, CreatedAtMixin):
    __tablename__ = "answers"

    id: Mapped[uuid.UUID] = uuid_pk()
    query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Resposta bruta do modelo, incluindo a confianca auto-reportada — guardada para
    # analise, mas nunca exibida ao usuario (ADR-0008, camada 5).
    raw_response: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    query: Mapped[Query] = relationship(back_populates="answer", lazy="raise")
    citations: Mapped[list[Citation]] = relationship(
        back_populates="answer",
        cascade="all, delete-orphan",
        order_by="Citation.rank",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Answer query={self.query_id} insufficient={self.insufficient_evidence}>"


class Citation(Base, CreatedAtMixin):
    """Vinculo entre uma resposta e o chunk que a fundamentou.

    Sobrevive a validacao de ADR-0008: so chega aqui uma citacao cujo identificador
    existia de fato no conjunto recuperado.
    """

    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = uuid_pk()
    answer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), nullable=False
    )

    # RESTRICT: uma citacao nunca pode ficar orfa. Excluir um documento citado exige
    # decisao explicita, nao cascata silenciosa — e o que sustenta a rastreabilidade.
    document_chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="RESTRICT"), nullable=False
    )

    # Denormalizado para as agregacoes do Intelligence ("documentos mais utilizados"),
    # que de outro modo precisariam de dois joins. Imutavel apos a escrita.
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )

    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)

    answer: Mapped[Answer] = relationship(back_populates="citations", lazy="raise")
    chunk: Mapped[DocumentChunk] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("answer_id", "document_chunk_id"),
        Index("ix_citations_version", "document_version_id"),
        CheckConstraint("rank >= 0", name="rank_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Citation answer={self.answer_id} rank={self.rank}>"
