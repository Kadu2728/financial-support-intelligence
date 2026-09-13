"""Arquivos no banco (storage backend `db`).

Revision ID: 0002_stored_files
Revises: 0001_initial_schema
Create Date: 2026-09-13

Tabela usada apenas quando STORAGE_BACKEND=db (ADR-0007, revisao). Existe em todo
banco — vazia quando o backend e outro — para que trocar de backend seja so uma
variavel de ambiente, sem migration condicional.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_stored_files"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_files",
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_stored_files")),
    )


def downgrade() -> None:
    op.drop_table("stored_files")
