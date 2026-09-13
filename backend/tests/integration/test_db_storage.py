"""Storage no Postgres contra banco real: upsert, leitura, remocao, ausencia."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.storage.base import ObjectNotFound
from app.integrations.storage.db import DbStorage
from tests.integration.conftest import requires_db

pytestmark = pytest.mark.integration


@requires_db
async def test_ciclo_completo(session_factory: async_sessionmaker[AsyncSession]) -> None:
    storage = DbStorage(session_factory)
    chave = f"documents/teste/{uuid.uuid4()}.pdf"
    try:
        assert await storage.exists(chave) is False
        with pytest.raises(ObjectNotFound):
            await storage.get(chave)

        await storage.put(chave, b"%PDF-1.7 primeiro", content_type="application/pdf")
        assert await storage.exists(chave) is True
        assert await storage.get(chave) == b"%PDF-1.7 primeiro"

        # Sobrescrever substitui por completo, como no disco e no S3.
        await storage.put(chave, b"%PDF-1.7 segundo, maior", content_type="application/pdf")
        assert await storage.get(chave) == b"%PDF-1.7 segundo, maior"

        async with session_factory() as session:
            tamanho, tipo = (
                await session.execute(
                    text("SELECT size_bytes, content_type FROM stored_files WHERE key = :k"),
                    {"k": chave},
                )
            ).one()
        assert tamanho == len(b"%PDF-1.7 segundo, maior")
        assert tipo == "application/pdf"

        await storage.delete(chave)
        assert await storage.exists(chave) is False
        # Idempotente: remover de novo nao e erro.
        await storage.delete(chave)
    finally:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM stored_files WHERE key = :k"), {"k": chave})
            await session.commit()


@requires_db
async def test_conteudo_binario_sobrevive_integro(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """BYTEA nao pode alterar um unico byte: o checksum SHA-256 do arquivo e
    conferido no upload e o download precisa devolver o mesmo objeto."""
    storage = DbStorage(session_factory)
    chave = f"documents/teste/{uuid.uuid4()}.bin"
    conteudo = bytes(range(256)) * 64  # 16 KB cobrindo todos os bytes, inclusive NUL
    try:
        await storage.put(chave, conteudo, content_type="application/octet-stream")
        assert await storage.get(chave) == conteudo
    finally:
        await storage.delete(chave)
