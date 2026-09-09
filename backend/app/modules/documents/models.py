"""Documentos, versoes e chunks.

A separacao entre `Document` (identidade logica) e `DocumentVersion` (arquivo concreto
e seus chunks) e o que mantem as citacoes historicas honestas quando um manual e
atualizado. Justificativa em docs/adr/0005-versionamento-de-documentos.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import EMBEDDING_DIM, Base, CreatedAtMixin, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.modules.ingestion.models import ProcessingJob
    from app.modules.users.models import User


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


document_status_enum = Enum(
    DocumentStatus,
    name="doc_status",
    values_callable=lambda enum: [member.value for member in enum],
)

# Configuracao de full-text search. Fixada em 'portuguese' no DDL porque
# `to_tsvector(regconfig, text)` so e IMMUTABLE — requisito de coluna gerada — quando o
# primeiro argumento e uma constante. A variante de um argumento usa
# `default_text_search_config`, e apenas STABLE, e o PostgreSQL rejeita a coluna.
FTS_CONFIG = "portuguese"


class Document(Base, TimestampMixin):
    """Identidade estavel. "Manual de Cadastro" e um Document, para sempre."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # RESTRICT: apagar um usuario nao pode levar junto os documentos que ele subiu.
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # Soft delete: as citacoes historicas apontam para versoes deste documento e
    # precisam continuar resolviveis (ver ADR-0005).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    uploader: Mapped[User] = relationship(lazy="raise")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        # Listagem de documentos ativos, ordenada por atualizacao.
        Index(
            "ix_documents_active",
            "updated_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Busca por titulo na tela de administracao. pg_trgm suporta ILIKE '%termo%',
        # que um btree comum nao consegue acelerar.
        Index(
            "ix_documents_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<Document {self.title!r}>"


class DocumentVersion(Base, CreatedAtMixin):
    """Arquivo concreto e dono dos chunks."""

    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        document_status_enum, nullable=False, default=DocumentStatus.PENDING
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # SHA-256 em hex. Detecta re-upload do mesmo arquivo antes de gastar embeddings.
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # Gerada pelo servidor a partir de UUIDs, nunca derivada do nome enviado pelo
    # usuario — elimina path traversal por construcao (ADR-0007).
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship(back_populates="versions", lazy="raise")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("document_id", "version_number"),
        UniqueConstraint("checksum_sha256"),
        # No maximo uma versao corrente por documento. Um indice parcial unico expressa
        # essa invariante no banco; garanti-la apenas em codigo permitiria que uma
        # condicao de corrida deixasse duas versoes correntes e duplicasse a busca.
        Index(
            "uq_document_versions_current",
            "document_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        # Fila da tela de administracao: versoes ainda em processamento.
        Index("ix_document_versions_status", "status", "created_at"),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentVersion doc={self.document_id} v{self.version_number} {self.status.value}>"
        )


class DocumentChunk(Base, CreatedAtMixin):
    """Unidade de recuperacao e de citacao.

    Os campos de posicao (`section_path`, `page_number`, `char_start`/`char_end`) nao
    sao acessorios: sao eles que transformam "a IA respondeu" em "a IA respondeu e eu
    posso conferir onde".
    """

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    # "3. Cadastro > 3.2 Atualizacao Cadastral" — o que aparece na citacao exibida.
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Offsets no texto normalizado: permitem destacar o trecho exato no visualizador.
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)

    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    # Sem isto, trocar de modelo de embedding torna impossivel saber o que re-gerar, e
    # vetores de espacos diferentes convivendo no mesmo indice produzem ranking sem
    # significado — sem falhar visivelmente.
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)

    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(f"to_tsvector('{FTS_CONFIG}', content)", persisted=True),
        nullable=False,
    )

    version: Mapped[DocumentVersion] = relationship(back_populates="chunks", lazy="raise")

    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_index"),
        # Perna semantica da busca hibrida (ADR-0002). HNSW: melhor recall/latencia que
        # ivfflat e nao exige treino previo sobre os dados.
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Perna lexical da busca hibrida.
        Index("ix_document_chunks_tsv", "tsv", postgresql_using="gin"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint("char_end > char_start", name="char_range_valid"),
        CheckConstraint("content_tokens > 0", name="content_tokens_positive"),
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk v={self.document_version_id} #{self.chunk_index}>"
