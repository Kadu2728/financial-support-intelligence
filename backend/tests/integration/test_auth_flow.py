"""Autenticacao contra PostgreSQL real.

Cobre o que os repositories fake nao alcancam: o comportamento TRANSACIONAL.

A deteccao de reuso revoga as sessoes e em seguida levanta uma excecao — que dispara
o rollback na borda da requisicao. Sem um commit explicito, a revogacao e desfeita e a
defesa nao existe. Um fake em memoria nao tem transacao, entao passa nos dois casos:
so um banco de verdade distingue.
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
from app.core.errors import UnauthorizedError
from app.db.session import create_engine, create_session_factory
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.auth.service import AuthService
from app.modules.users.models import Role
from app.modules.users.repository import UserRepository

pytestmark = pytest.mark.integration

DATABASE_URL = os.getenv("DATABASE_URL", "")
SENHA = "senha-de-teste-comprida-2026"

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
    )


@pytest_asyncio.fixture
async def session_factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(settings)
    yield create_session_factory(engine)
    await engine.dispose()


def build_service(settings: Settings, session: AsyncSession) -> AuthService:
    return AuthService(
        settings=settings,
        session=session,
        users=UserRepository(session),
        refresh_tokens=RefreshTokenRepository(session),
    )


@pytest_asyncio.fixture
async def usuario(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[str]:
    """Usuario descartavel, removido ao final junto de seus tokens."""
    email = f"teste-{uuid.uuid4().hex[:12]}@bancoexemplo.com.br"

    async with session_factory() as session:
        user = await build_service(settings, session).create_user(
            email=email, password=SENHA, full_name="Usuario de Teste", role=Role.ANALYST
        )
        user_id = user.id
        await session.commit()

    yield email

    async with session_factory() as session:
        await session.execute(
            text("DELETE FROM refresh_tokens WHERE user_id = :id"), {"id": user_id}
        )
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await session.commit()


@requires_db
async def test_login_persiste_o_refresh_token(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], usuario: str
) -> None:
    async with session_factory() as session:
        tokens, user = await build_service(settings, session).login(email=usuario, password=SENHA)
        await session.commit()

    async with session_factory() as session:
        total = await session.execute(
            text("SELECT count(*) FROM refresh_tokens WHERE user_id = :id AND revoked_at IS NULL"),
            {"id": user.id},
        )
        assert total.scalar_one() == 1
    assert tokens.access_token


@requires_db
async def test_rotacao_revoga_o_token_anterior(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], usuario: str
) -> None:
    async with session_factory() as session:
        tokens, _ = await build_service(settings, session).login(email=usuario, password=SENHA)
        await session.commit()

    async with session_factory() as session:
        novos, _ = await build_service(settings, session).refresh(
            refresh_token=tokens.refresh_token
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(UnauthorizedError):
            await build_service(settings, session).refresh(refresh_token=tokens.refresh_token)
    assert novos.refresh_token != tokens.refresh_token


@requires_db
async def test_reuso_derruba_as_sessoes_apesar_do_rollback(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], usuario: str
) -> None:
    """O teste que justifica esta suite existir.

    A deteccao de reuso escreve e depois levanta excecao. Aqui a sessao e descartada
    sem commit — exatamente como a borda da requisicao faz em caso de erro. Se a
    revogacao nao tiver sido commitada explicitamente, ela some, e o token roubado
    continua valendo.
    """
    service_session = session_factory()

    # Tres sessoes legitimas, como tres dispositivos conectados.
    async with session_factory() as session:
        service = build_service(settings, session)
        roubado, user = await service.login(email=usuario, password=SENHA)
        await service.login(email=usuario, password=SENHA)
        await service.login(email=usuario, password=SENHA)
        await session.commit()

    # O usuario legitimo renova: o token roubado passa a estar revogado.
    async with session_factory() as session:
        await build_service(settings, session).refresh(refresh_token=roubado.refresh_token)
        await session.commit()

    # O atacante usa a copia. A excecao faz a sessao ser descartada SEM commit.
    async with service_session as session:
        with pytest.raises(UnauthorizedError):
            await build_service(settings, session).refresh(refresh_token=roubado.refresh_token)
        await session.rollback()

    # Em uma conexao nova: nenhuma sessao pode ter sobrevivido.
    async with session_factory() as session:
        ativos = await session.execute(
            text("SELECT count(*) FROM refresh_tokens WHERE user_id = :id AND revoked_at IS NULL"),
            {"id": user.id},
        )
        assert ativos.scalar_one() == 0, (
            "a revogacao por deteccao de reuso nao sobreviveu ao rollback: "
            "o token roubado continua valido"
        )


@requires_db
async def test_email_duplicado_e_recusado_pelo_banco(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], usuario: str
) -> None:
    """CITEXT em acao pela camada de servico, com a caixa trocada."""
    from sqlalchemy.exc import IntegrityError

    # `pytest.raises` e sincrono e nao pode ser combinado com o `async with` numa
    # unica clausula, apesar de o ruff sugerir (SIM117).
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await build_service(settings, session).create_user(
                email=usuario.upper(), password=SENHA, full_name="Duplicado", role=Role.ANALYST
            )
