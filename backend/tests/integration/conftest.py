"""Fixtures compartilhadas dos testes de integracao (Fases 5b em diante).

Os arquivos das fases anteriores definem as suas proprias; um fixture local de mesmo
nome tem precedencia sobre estes, entao nada muda para eles.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Environment, Settings
from app.db.session import create_engine, create_session_factory
from app.modules.users.models import Role, User
from tests.fakes import FakeStorage

DATABASE_URL = os.getenv("DATABASE_URL", "")

requires_db = pytest.mark.skipif(
    not DATABASE_URL or "localhost" in DATABASE_URL,
    reason="defina DATABASE_URL apontando para um PostgreSQL real",
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        app_env=Environment.TEST,
        jwt_secret_key="segredo-de-teste-com-tamanho-suficiente",
        worker_enabled=False,
    )


@pytest_asyncio.fixture
async def session_factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(settings)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


async def _limpar_usuario(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Remove tudo que o usuario criou, na ordem inversa das dependencias.

    As FKs RESTRICT de `citations` existem para proteger dados reais; no teste a
    limpeza precisa passar por elas explicitamente.
    """
    comandos = [
        "DELETE FROM feedback WHERE user_id = :id",
        """DELETE FROM citations WHERE answer_id IN (
               SELECT a.id FROM answers a JOIN queries q ON q.id = a.query_id
               WHERE q.user_id = :id)""",
        "DELETE FROM answers WHERE query_id IN (SELECT id FROM queries WHERE user_id = :id)",
        "DELETE FROM queries WHERE user_id = :id",
        """DELETE FROM processing_jobs WHERE document_version_id IN (
               SELECT dv.id FROM document_versions dv
               JOIN documents d ON d.id = dv.document_id WHERE d.uploaded_by = :id)""",
        """DELETE FROM document_versions WHERE document_id IN (
               SELECT id FROM documents WHERE uploaded_by = :id)""",
        "DELETE FROM documents WHERE uploaded_by = :id",
        "DELETE FROM refresh_tokens WHERE user_id = :id",
        "DELETE FROM users WHERE id = :id",
    ]
    for comando in comandos:
        await session.execute(text(comando), {"id": user_id})


@pytest_asyncio.fixture
async def admin(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[User]:
    async with session_factory() as session:
        user = User(
            email=f"admin-{uuid.uuid4().hex[:12]}@bancoexemplo.com.br",
            password_hash="x",
            full_name="Admin de Teste",
            role=Role.ADMIN,
        )
        session.add(user)
        await session.commit()

    yield user

    async with session_factory() as session:
        await _limpar_usuario(session, user.id)
        await session.commit()


@pytest_asyncio.fixture
async def analista(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[User]:
    async with session_factory() as session:
        user = User(
            email=f"analista-{uuid.uuid4().hex[:12]}@bancoexemplo.com.br",
            password_hash="x",
            full_name="Analista de Teste",
            role=Role.ANALYST,
        )
        session.add(user)
        await session.commit()

    yield user

    async with session_factory() as session:
        await _limpar_usuario(session, user.id)
        await session.commit()
