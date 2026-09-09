"""Base declarativa e convencoes compartilhadas por todos os modelos.

Duas decisoes valem por si:

1. **Convencao de nomes de constraints.** Sem ela, o PostgreSQL nomeia constraints
   automaticamente e o Alembic gera migrations com nomes que variam entre ambientes —
   o `downgrade` entao falha porque tenta remover uma constraint com nome diferente do
   que existe. A convencao torna os nomes deterministicos.

2. **`lazy="raise"` como padrao em todo relationship.** Em SQLAlchemy async, um
   lazy-load acidental levanta `MissingGreenlet` em runtime, no lugar mais inconveniente
   possivel. Com `lazy="raise"`, o erro aparece na primeira execucao do teste, com uma
   mensagem que diz exatamente o que fazer: carregar explicitamente com `selectinload`.
   Isso tambem elimina a classe inteira de bugs N+1 por acidente.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Dimensao dos embeddings. Fixada no schema — trocar exige migration E re-embeddar
# todo o acervo, por isso nao e configuravel por variavel de ambiente.
# Escolha justificada em docs/rag-design.md: HNSW no pgvector indexa ate 2000 dimensoes.
EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    """Chave primaria UUID gerada na aplicacao.

    Gerar do lado do cliente (e nao com `gen_random_uuid()` no banco) permite montar o
    grafo de objetos e conhecer os ids antes do INSERT — necessario para inserir um
    documento e seus chunks em uma unica transacao (docs/architecture.md §5).
    """
    return mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """`created_at` e `updated_at` em UTC, mantidos pelo banco."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CreatedAtMixin:
    """So `created_at`, para tabelas append-only (citations, feedback, jobs)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
