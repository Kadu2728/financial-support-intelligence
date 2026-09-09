"""Schema inicial.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-09

Escrita a mao, nao por autogenerate, porque a ordem importa: extensoes precisam existir
antes dos tipos de coluna que dependem delas (VECTOR, CITEXT), e os tipos ENUM antes das
tabelas que os usam. O autogenerate nao modela extensoes.

O `downgrade` remove tabelas e tipos, mas NAO as extensoes: outra aplicacao pode
compartilhar o banco, e `DROP EXTENSION vector` derrubaria os dados dela junto.
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 768

# Nome -> valores. Criados e removidos explicitamente: o Alembic cria o tipo junto da
# primeira tabela que o referencia, mas nunca o remove no downgrade — o que faz um
# `downgrade` seguido de `upgrade` falhar com "type already exists".
ENUMS: dict[str, tuple[str, ...]] = {
    "user_role": ("ADMIN", "ANALYST"),
    "doc_status": ("PENDING", "PROCESSING", "READY", "FAILED", "SUPERSEDED"),
    "job_status": ("PENDING", "RUNNING", "COMPLETED", "FAILED"),
    "job_type": ("INGEST",),
    "query_status": ("SUCCESS", "INSUFFICIENT_EVIDENCE", "FAILED"),
    "feedback_rating": ("POSITIVE", "NEGATIVE"),
    "feedback_reason": ("INCORRECT", "INCOMPLETE", "WRONG_SOURCE", "OUTDATED", "OTHER"),
}


def _enum(name: str) -> postgresql.ENUM:
    """Referencia um ENUM ja criado, sem tentar cria-lo de novo."""
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    # --- Extensoes ---------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")  # embeddings + busca vetorial
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # ILIKE '%termo%' indexado
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")  # e-mail case-insensitive

    # --- Tipos ENUM --------------------------------------------------------
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(op.get_bind(), checkfirst=True)

    # --- users -------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", _enum("user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )

    # --- refresh_tokens ----------------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        "ix_refresh_tokens_user_active",
        "refresh_tokens",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # --- documents ---------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_documents_uploaded_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(
        "ix_documents_active",
        "documents",
        ["updated_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_documents_title_trgm",
        "documents",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )

    # --- document_versions -------------------------------------------------
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", _enum("doc_status"), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name=op.f("ck_document_versions_version_number_positive"),
        ),
        sa.CheckConstraint(
            "file_size_bytes > 0", name=op.f("ck_document_versions_file_size_positive")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name=op.f("uq_document_versions_document_id_version_number"),
        ),
        sa.UniqueConstraint("checksum_sha256", name=op.f("uq_document_versions_checksum_sha256")),
    )
    op.create_index("ix_document_versions_status", "document_versions", ["status", "created_at"])
    # Invariante: no maximo uma versao corrente por documento (ADR-0005).
    op.create_index(
        "uq_document_versions_current",
        "document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    # --- document_chunks ---------------------------------------------------
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_tokens", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("section_label", sa.String(64), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        # to_tsvector de DOIS argumentos: a variante de um argumento e apenas STABLE e
        # o PostgreSQL a rejeita em coluna gerada.
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('portuguese', content)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0", name=op.f("ck_document_chunks_chunk_index_non_negative")
        ),
        sa.CheckConstraint(
            "char_end > char_start", name=op.f("ck_document_chunks_char_range_valid")
        ),
        sa.CheckConstraint(
            "content_tokens > 0",
            name=op.f("ck_document_chunks_content_tokens_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_document_chunks_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name=op.f("uq_document_chunks_document_version_id_chunk_index"),
        ),
    )
    # As duas pernas da busca hibrida (ADR-0002).
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_document_chunks_tsv", "document_chunks", ["tsv"], postgresql_using="gin")

    # --- processing_jobs ---------------------------------------------------
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", _enum("job_type"), nullable=False),
        sa.Column("status", _enum("job_status"), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_processing_jobs_attempts_non_negative")),
        sa.CheckConstraint(
            "max_attempts > 0", name=op.f("ck_processing_jobs_max_attempts_positive")
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_processing_jobs_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_jobs")),
    )
    # Indice de claim do worker: FOR UPDATE SKIP LOCKED percorre esta ordem (ADR-0004).
    op.create_index(
        "ix_processing_jobs_claimable",
        "processing_jobs",
        ["created_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_processing_jobs_running",
        "processing_jobs",
        ["started_at"],
        postgresql_where=sa.text("status = 'RUNNING'"),
    )
    op.create_index("ix_processing_jobs_version", "processing_jobs", ["document_version_id"])

    # --- queries -----------------------------------------------------------
    op.create_table(
        "queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", _enum("query_status"), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("chunks_retrieved", sa.Integer(), nullable=False),
        sa.Column("top_score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("retrieval_ms", sa.Integer(), nullable=True),
        sa.Column("generation_ms", sa.Integer(), nullable=True),
        sa.Column("total_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunks_retrieved >= 0", name=op.f("ck_queries_chunks_retrieved_non_negative")
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_queries_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_queries_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_queries")),
    )
    op.create_index("ix_queries_user_created", "queries", ["user_id", sa.text("created_at DESC")])
    op.create_index("ix_queries_created", "queries", [sa.text("created_at DESC")])
    # Perguntas que o acervo nao respondeu: o indicador mais valioso do produto.
    op.create_index(
        "ix_queries_gaps",
        "queries",
        ["created_at"],
        postgresql_where=sa.text("status <> 'SUCCESS'"),
    )

    # --- answers -----------------------------------------------------------
    op.create_table(
        "answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("query_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("insufficient_evidence", sa.Boolean(), nullable=False),
        sa.Column("raw_response", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["query_id"],
            ["queries.id"],
            name=op.f("fk_answers_query_id_queries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_answers")),
        sa.UniqueConstraint("query_id", name=op.f("uq_answers_query_id")),
    )

    # --- citations ---------------------------------------------------------
    op.create_table(
        "citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("answer_id", sa.Uuid(), nullable=False),
        sa.Column("document_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rank >= 0", name=op.f("ck_citations_rank_non_negative")),
        sa.ForeignKeyConstraint(
            ["answer_id"],
            ["answers.id"],
            name=op.f("fk_citations_answer_id_answers"),
            ondelete="CASCADE",
        ),
        # RESTRICT: uma citacao nunca fica orfa. E o que sustenta a rastreabilidade.
        sa.ForeignKeyConstraint(
            ["document_chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_citations_document_chunk_id_document_chunks"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_citations_document_version_id_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_citations")),
        sa.UniqueConstraint(
            "answer_id",
            "document_chunk_id",
            name=op.f("uq_citations_answer_id_document_chunk_id"),
        ),
    )
    op.create_index("ix_citations_version", "citations", ["document_version_id"])

    # --- feedback ----------------------------------------------------------
    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("query_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rating", _enum("feedback_rating"), nullable=False),
        sa.Column("reason", _enum("feedback_reason"), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["query_id"],
            ["queries.id"],
            name=op.f("fk_feedback_query_id_queries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_feedback_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint("query_id", "user_id", name=op.f("uq_feedback_query_id_user_id")),
    )
    op.create_index("ix_feedback_rating_created", "feedback", ["rating", "created_at"])


def downgrade() -> None:
    # Ordem inversa das dependencias. Os indices caem junto com as tabelas.
    for table in (
        "feedback",
        "citations",
        "answers",
        "queries",
        "processing_jobs",
        "document_chunks",
        "document_versions",
        "documents",
        "refresh_tokens",
        "users",
    ):
        op.drop_table(table)

    # Os tipos ENUM nao caem com as tabelas. Sem isto, um downgrade seguido de upgrade
    # falha com "type already exists".
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)

    # As extensoes ficam. `DROP EXTENSION vector` derrubaria os dados de qualquer outra
    # aplicacao que compartilhe este banco.
