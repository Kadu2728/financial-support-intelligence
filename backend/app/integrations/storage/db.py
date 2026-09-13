"""Armazenamento dos arquivos no proprio PostgreSQL (ADR-0007, revisao).

Existe para o caso em que o runtime nao tem disco persistente nem um bucket de objetos
a mao — o plano gratuito do Render, por exemplo. Cada arquivo vira uma linha com o
conteudo em BYTEA.

Quando faz sentido: acervos pequenos — dezenas de manuais, algumas dezenas de MB.
O Neon cobra por armazenamento e o Postgres nao e um object store; a partir de
centenas de MB, a resposta certa e o backend S3 (R2), que ja existe. A troca e uma
variavel de ambiente.

Semantica igual a de um object store: `put` e duravel quando retorna, em transacao
propria e curta. O worker e a API compartilham a mesma `session_factory`, mas nunca
a mesma sessao — a de quem chama pode estar no meio de outra transacao.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, LargeBinary, String, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.integrations.storage.base import ObjectNotFound, StorageError


class StoredFile(Base):
    __tablename__ = "stored_files"

    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<StoredFile {self.key} {self.size_bytes}B>"


class DbStorage:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        # Upsert: sobrescrever substitui por completo, como no disco e no S3.
        comando = insert(StoredFile).values(
            key=key, content=data, content_type=content_type, size_bytes=len(data)
        )
        comando = comando.on_conflict_do_update(
            index_elements=[StoredFile.key],
            set_={
                "content": comando.excluded.content,
                "content_type": comando.excluded.content_type,
                "size_bytes": comando.excluded.size_bytes,
            },
        )
        try:
            async with self._sessions() as session:
                await session.execute(comando)
                await session.commit()
        except SQLAlchemyError as exc:
            raise StorageError(f"falha ao gravar {key}") from exc

    async def get(self, key: str) -> bytes:
        try:
            async with self._sessions() as session:
                conteudo = await session.scalar(
                    select(StoredFile.content).where(StoredFile.key == key)
                )
        except SQLAlchemyError as exc:
            raise StorageError(f"falha ao ler {key}") from exc
        if conteudo is None:
            raise ObjectNotFound(key)
        return bytes(conteudo)

    async def delete(self, key: str) -> None:
        try:
            async with self._sessions() as session:
                await session.execute(delete(StoredFile).where(StoredFile.key == key))
                await session.commit()
        except SQLAlchemyError as exc:
            raise StorageError(f"falha ao remover {key}") from exc

    async def exists(self, key: str) -> bool:
        try:
            async with self._sessions() as session:
                encontrado = await session.scalar(
                    select(StoredFile.key).where(StoredFile.key == key)
                )
        except SQLAlchemyError as exc:
            raise StorageError(f"falha ao consultar {key}") from exc
        return encontrado is not None
