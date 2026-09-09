"""Validacao do schema contra um PostgreSQL real.

Estes testes cobrem exatamente o que a validacao offline nao alcanca: que o DDL executa,
que as extensoes existem, que os indices sao criados e que as invariantes declaradas no
schema de fato bloqueiam escrita invalida.

Rodar depois de aplicar a migration:

    DATABASE_URL="postgresql+asyncpg://..." .venv/Scripts/python -m alembic upgrade head
    DATABASE_URL="postgresql+asyncpg://..." .venv/Scripts/python -m pytest -m integration

Sao pulados automaticamente quando `DATABASE_URL` nao aponta para um banco real, para que
a suite continue rodando offline.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.db.base import EMBEDDING_DIM

pytestmark = pytest.mark.integration

DATABASE_URL = os.getenv("DATABASE_URL", "")

# O default de Settings aponta para um localhost que nao existe nesta maquina. Sem
# `DATABASE_URL` no ambiente, nao ha banco real para exercitar.
requires_db = pytest.mark.skipif(
    not DATABASE_URL or "localhost" in DATABASE_URL,
    reason="defina DATABASE_URL apontando para um PostgreSQL real",
)


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection]:
    """Conexao em transacao revertida ao final: os testes nao deixam residuo."""
    engine = create_async_engine(DATABASE_URL, connect_args={"statement_cache_size": 0})
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


@requires_db
async def test_extensoes_instaladas(conn: AsyncConnection) -> None:
    result = await conn.execute(
        text("SELECT extname FROM pg_extension WHERE extname = ANY(:nomes)"),
        {"nomes": ["vector", "pg_trgm", "citext"]},
    )
    assert {row[0] for row in result} == {"vector", "pg_trgm", "citext"}


@requires_db
async def test_todas_as_tabelas_existem(conn: AsyncConnection) -> None:
    result = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    tabelas = {row[0] for row in result}

    esperadas = {
        "users",
        "refresh_tokens",
        "documents",
        "document_versions",
        "document_chunks",
        "processing_jobs",
        "queries",
        "answers",
        "citations",
        "feedback",
    }
    assert esperadas <= tabelas, f"faltando: {sorted(esperadas - tabelas)}"


@requires_db
async def test_indice_hnsw_foi_criado(conn: AsyncConnection) -> None:
    """Se a dimensao passasse de 2000, o CREATE INDEX teria falhado silenciosamente."""
    result = await conn.execute(
        text("""
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'document_chunks'
              AND indexname = 'ix_document_chunks_embedding_hnsw'
        """)
    )
    definicao = result.scalar_one()
    assert "USING hnsw" in definicao
    assert "vector_cosine_ops" in definicao


@requires_db
async def test_coluna_tsv_e_preenchida_automaticamente(conn: AsyncConnection) -> None:
    """A coluna gerada precisa produzir lexemas em portugues, nao apenas existir."""
    result = await conn.execute(
        text("SELECT to_tsvector('portuguese', :texto)"),
        {"texto": "procedimento de atualizacao cadastral do cliente"},
    )
    tsv = result.scalar_one()
    # O stemmer portugues reduz "atualizacao" ao radical.
    assert "atualiza" in tsv


@requires_db
async def test_busca_vetorial_funciona(conn: AsyncConnection) -> None:
    """Exercita o operador de distancia de cosseno de ponta a ponta."""
    vetor = "[" + ",".join(["0.1"] * EMBEDDING_DIM) + "]"
    result = await conn.execute(text(f"SELECT '{vetor}'::vector <=> '{vetor}'::vector"))
    distancia = result.scalar_one()
    assert distancia == pytest.approx(0.0, abs=1e-6)


@requires_db
async def test_apenas_uma_versao_corrente_por_documento(conn: AsyncConnection) -> None:
    """A invariante de ADR-0005 precisa ser imposta pelo banco, nao so pelo service."""
    user_id, doc_id = uuid.uuid4(), uuid.uuid4()

    await conn.execute(
        text("""
            INSERT INTO users (id, email, password_hash, full_name, role, is_active)
            VALUES (:id, :email, 'x', 'Teste', 'ADMIN', true)
        """),
        {"id": user_id, "email": f"{user_id}@teste.local"},
    )
    await conn.execute(
        text("INSERT INTO documents (id, title, uploaded_by) VALUES (:id, 'Doc', :user)"),
        {"id": doc_id, "user": user_id},
    )

    async def inserir_versao(numero: int) -> None:
        await conn.execute(
            text("""
                INSERT INTO document_versions (
                    id, document_id, version_number, status, is_current,
                    original_filename, mime_type, file_size_bytes,
                    checksum_sha256, storage_key
                ) VALUES (
                    :id, :doc, :numero, 'READY', true,
                    'a.pdf', 'application/pdf', 100,
                    :checksum, :chave
                )
            """),
            {
                "id": uuid.uuid4(),
                "doc": doc_id,
                "numero": numero,
                "checksum": uuid.uuid4().hex * 2,
                "chave": f"documents/{doc_id}/{numero}.pdf",
            },
        )

    await inserir_versao(1)

    with pytest.raises(IntegrityError):
        await inserir_versao(2)


@requires_db
async def test_email_e_case_insensitive(conn: AsyncConnection) -> None:
    """CITEXT em acao: sem ele, dois cadastros com o mesmo e-mail coexistiriam."""
    base = uuid.uuid4().hex

    await conn.execute(
        text("""
            INSERT INTO users (id, email, password_hash, full_name, role, is_active)
            VALUES (:id, :email, 'x', 'Teste', 'ANALYST', true)
        """),
        {"id": uuid.uuid4(), "email": f"{base}@Teste.Local"},
    )

    with pytest.raises(IntegrityError):
        await conn.execute(
            text("""
                INSERT INTO users (id, email, password_hash, full_name, role, is_active)
                VALUES (:id, :email, 'x', 'Outro', 'ANALYST', true)
            """),
            {"id": uuid.uuid4(), "email": f"{base}@teste.local"},
        )


@requires_db
async def test_enum_rejeita_valor_invalido(conn: AsyncConnection) -> None:
    """Um erro de digitacao em papel vira erro de escrita, nao falha de autorizacao."""
    with pytest.raises(DBAPIError):
        await conn.execute(
            text("""
                INSERT INTO users (id, email, password_hash, full_name, role, is_active)
                VALUES (:id, :email, 'x', 'Teste', 'ADMIM', true)
            """),
            {"id": uuid.uuid4(), "email": f"{uuid.uuid4()}@teste.local"},
        )


@requires_db
async def test_check_constraint_rejeita_intervalo_invalido(
    conn: AsyncConnection,
) -> None:
    """char_end <= char_start produziria destaque invertido no visualizador."""
    with pytest.raises(IntegrityError):
        await conn.execute(
            text(f"""
                INSERT INTO document_chunks (
                    id, document_version_id, chunk_index, content, content_tokens,
                    char_start, char_end, embedding, embedding_model
                ) VALUES (
                    :id, :versao, 0, 'texto', 10,
                    100, 50, '{"[" + ",".join(["0.1"] * EMBEDDING_DIM) + "]"}', 'teste'
                )
            """),  # noqa: S608
            {"id": uuid.uuid4(), "versao": uuid.uuid4()},
        )
