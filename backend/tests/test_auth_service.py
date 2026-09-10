"""Regra de negocio da autenticacao.

O foco esta nas decisoes que nao aparecem no contrato HTTP: quando um token e revogado,
o que acontece quando um token roubado e reutilizado, e por que a resposta de login e
sempre a mesma independente do motivo da falha.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from app.core.config import Environment, Settings
from app.core.errors import UnauthorizedError
from app.core.security import hash_password, hash_refresh_token
from app.modules.auth.service import (
    AuthService,
    InactiveUserError,
    InvalidCredentialsError,
)
from app.modules.users.models import Role, User
from tests.fakes import FakeRefreshTokenRepository, FakeUserRepository

SENHA = "senha-correta-do-analista"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env=Environment.TEST, jwt_secret_key="segredo-de-teste-com-tamanho-suficiente"
    )


def make_user(*, role: Role = Role.ANALYST, is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email="analista@bancoexemplo.com.br",
        password_hash=hash_password(SENHA),
        full_name="Analista de Suporte",
        role=role,
        is_active=is_active,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def user() -> User:
    return make_user()


@pytest.fixture
def tokens_repo() -> FakeRefreshTokenRepository:
    return FakeRefreshTokenRepository()


@pytest.fixture
def service(settings: Settings, user: User, tokens_repo: FakeRefreshTokenRepository) -> AuthService:
    return AuthService(
        settings=settings,
        users=cast("Any", FakeUserRepository([user])),
        refresh_tokens=cast("Any", tokens_repo),
    )


# --- Login -----------------------------------------------------------------


async def test_login_com_credenciais_validas_emite_par_de_tokens(
    service: AuthService, user: User
) -> None:
    tokens, autenticado = await service.login(email=user.email, password=SENHA)

    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.expires_in > 0
    assert autenticado.id == user.id


async def test_login_aceita_email_com_caixa_diferente(service: AuthService, user: User) -> None:
    """A coluna e CITEXT: o usuario nao deve ser punido por digitar com maiuscula."""
    _, autenticado = await service.login(email=user.email.upper(), password=SENHA)

    assert autenticado.id == user.id


async def test_senha_errada_e_email_inexistente_dao_o_mesmo_erro(
    service: AuthService, user: User
) -> None:
    """Distinguir os dois casos permitiria enumerar quais e-mails estao cadastrados."""
    with pytest.raises(InvalidCredentialsError) as senha_errada:
        await service.login(email=user.email, password="errada")

    with pytest.raises(InvalidCredentialsError) as email_inexistente:
        await service.login(email="ninguem@bancoexemplo.com.br", password=SENHA)

    assert senha_errada.value.message == email_inexistente.value.message
    assert senha_errada.value.status_code == email_inexistente.value.status_code


async def test_login_com_email_inexistente_gasta_tempo_de_verificacao(
    service: AuthService,
) -> None:
    """Sem o hash de descarte, a resposta voltaria em microssegundos e o tempo
    revelaria que a conta nao existe."""
    inicio = time.perf_counter()
    with pytest.raises(InvalidCredentialsError):
        await service.login(email="ninguem@bancoexemplo.com.br", password=SENHA)
    decorrido = time.perf_counter() - inicio

    # argon2 com parametros padrao leva dezenas de milissegundos.
    assert decorrido > 0.005


async def test_conta_desativada_e_recusada(settings: Settings) -> None:
    inativo = make_user(is_active=False)
    service = AuthService(
        settings=settings,
        users=cast("Any", FakeUserRepository([inativo])),
        refresh_tokens=cast("Any", FakeRefreshTokenRepository()),
    )

    with pytest.raises(InactiveUserError):
        await service.login(email=inativo.email, password=SENHA)


async def test_conta_desativada_com_senha_errada_nao_revela_que_existe(
    settings: Settings,
) -> None:
    """A checagem de `is_active` vem DEPOIS da senha: responder "desativada" para quem
    so chutou o e-mail confirmaria que a conta existe."""
    inativo = make_user(is_active=False)
    service = AuthService(
        settings=settings,
        users=cast("Any", FakeUserRepository([inativo])),
        refresh_tokens=cast("Any", FakeRefreshTokenRepository()),
    )

    with pytest.raises(InvalidCredentialsError):
        await service.login(email=inativo.email, password="chute")


async def test_login_registra_o_acesso(service: AuthService, user: User) -> None:
    await service.login(email=user.email, password=SENHA)
    # O repositorio fake guarda as chamadas; o real faz UPDATE em last_login_at.
    assert user.id in cast("Any", service)._users.logins_registrados


async def test_refresh_token_e_persistido_hasheado(
    service: AuthService, user: User, tokens_repo: FakeRefreshTokenRepository
) -> None:
    """Um vazamento do banco nao pode entregar tokens utilizaveis."""
    tokens, _ = await service.login(email=user.email, password=SENHA)

    guardado = tokens_repo.ativos[0]
    assert guardado.token_hash != tokens.refresh_token
    assert guardado.token_hash == hash_refresh_token(tokens.refresh_token)


# --- Rotacao ---------------------------------------------------------------


async def test_refresh_emite_novos_tokens(service: AuthService, user: User) -> None:
    antigos, _ = await service.login(email=user.email, password=SENHA)

    novos, _ = await service.refresh(refresh_token=antigos.refresh_token)

    assert novos.refresh_token != antigos.refresh_token
    assert novos.access_token != antigos.access_token


async def test_refresh_revoga_o_token_usado(
    service: AuthService, user: User, tokens_repo: FakeRefreshTokenRepository
) -> None:
    antigos, _ = await service.login(email=user.email, password=SENHA)

    await service.refresh(refresh_token=antigos.refresh_token)

    usado = await tokens_repo.get_by_hash(hash_refresh_token(antigos.refresh_token))
    assert usado is not None
    assert usado.revoked_at is not None
    assert len(tokens_repo.ativos) == 1


async def test_token_ja_usado_nao_funciona_de_novo(service: AuthService, user: User) -> None:
    antigos, _ = await service.login(email=user.email, password=SENHA)
    await service.refresh(refresh_token=antigos.refresh_token)

    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token=antigos.refresh_token)


async def test_reuso_de_token_derruba_todas_as_sessoes(
    service: AuthService, user: User, tokens_repo: FakeRefreshTokenRepository
) -> None:
    """O caso que justifica a rotacao.

    Sem deteccao de reuso, o atacante que copiou o token continuaria renovando ao lado
    do usuario legitimo, indefinidamente. Aqui, o token reutilizado derruba tudo e
    forca um login novo — que o atacante nao consegue fazer.
    """
    roubado, _ = await service.login(email=user.email, password=SENHA)
    # Duas outras sessoes legitimas, em outros dispositivos.
    await service.login(email=user.email, password=SENHA)
    await service.login(email=user.email, password=SENHA)

    # O usuario legitimo renova: o token roubado passa a estar revogado.
    await service.refresh(refresh_token=roubado.refresh_token)
    assert len(tokens_repo.ativos) == 3

    # O atacante tenta usar a copia que guardou.
    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token=roubado.refresh_token)

    assert tokens_repo.ativos == []


async def test_refresh_expirado_e_recusado(
    service: AuthService, user: User, tokens_repo: FakeRefreshTokenRepository
) -> None:
    tokens, _ = await service.login(email=user.email, password=SENHA)
    guardado = tokens_repo.ativos[0]
    guardado.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token=tokens.refresh_token)


async def test_refresh_desconhecido_e_recusado(service: AuthService) -> None:
    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token="token-que-nunca-existiu")


async def test_refresh_de_usuario_desativado_e_recusado(service: AuthService, user: User) -> None:
    """Desativar uma conta precisa encerrar as sessoes ativas, nao apenas impedir
    novos logins."""
    tokens, _ = await service.login(email=user.email, password=SENHA)
    user.is_active = False

    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token=tokens.refresh_token)


# --- Logout ----------------------------------------------------------------


async def test_logout_revoga_a_sessao(
    service: AuthService, user: User, tokens_repo: FakeRefreshTokenRepository
) -> None:
    tokens, _ = await service.login(email=user.email, password=SENHA)

    await service.logout(refresh_token=tokens.refresh_token)

    assert tokens_repo.ativos == []
    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token=tokens.refresh_token)


async def test_logout_com_token_desconhecido_nao_falha(service: AuthService) -> None:
    """Idempotente: o cliente ja descartou o cookie, e um erro aqui so produziria
    alerta inutil para o usuario."""
    await service.logout(refresh_token="nunca-existiu")


async def test_logout_duas_vezes_nao_falha(service: AuthService, user: User) -> None:
    tokens, _ = await service.login(email=user.email, password=SENHA)

    await service.logout(refresh_token=tokens.refresh_token)
    await service.logout(refresh_token=tokens.refresh_token)


async def test_logout_all_derruba_todos_os_dispositivos(
    service: AuthService, user: User, tokens_repo: FakeRefreshTokenRepository
) -> None:
    await service.login(email=user.email, password=SENHA)
    await service.login(email=user.email, password=SENHA)

    revogadas = await service.logout_all(user_id=user.id)

    assert revogadas == 2
    assert tokens_repo.ativos == []
