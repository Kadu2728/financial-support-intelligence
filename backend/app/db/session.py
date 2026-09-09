"""Engine, sessao e dependency de banco.

Configuracao de pool pensada para Neon serverless (docs/architecture.md §11):

- Usar SEMPRE a connection string *pooled* (host com `-pooler`). O Neon escala para zero;
  o pooler absorve o cold start em vez de deixar cada conexao pagar por ele.
- `pool_pre_ping=True`: o Neon derruba conexoes ociosas. Sem o ping, a primeira query
  depois de um periodo parado falha com "connection was closed".
- Pool pequeno: o plano gratuito do Neon tem limite baixo de conexoes, e a aplicacao e
  I/O-bound em chamadas ao Gemini, nao em concorrencia de banco.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        str(settings.database_url),
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=300,
        # asyncpg faz cache de prepared statements por conexao. Atras de um pooler em
        # modo transaction, a conexao fisica muda entre requisicoes e o cache passa a
        # apontar para statements que nao existem mais naquela sessao.
        connect_args={"statement_cache_size": 0},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        # Sem isso, acessar um atributo apos o commit dispara refresh — que em async
        # levanta MissingGreenlet se estiver fora do contexto da sessao.
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Uma sessao por requisicao, com commit no sucesso e rollback no erro.

    A transacao e gerenciada aqui, na borda, e nao dentro dos services: um caso de uso
    que escreve em varias tabelas (documento + versao + job de processamento) precisa
    ser atomico, e isso so e possivel se todos compartilharem a mesma transacao.
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
