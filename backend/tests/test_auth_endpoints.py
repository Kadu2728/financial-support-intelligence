"""Contrato HTTP da autenticacao e da autorizacao.

Cobre o que o service nao alcanca: formato de resposta, status codes, e a barreira de
papel aplicada de fato nas rotas. O teste de que um ANALYST recebe 403 numa rota de
ADMIN e o criterio de pronto desta fase.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Environment, Settings
from app.core.dependencies import get_session
from app.core.security import hash_password
from app.main import create_app
from app.modules.auth.dependencies import get_auth_service, get_user_repository
from app.modules.auth.service import AuthService
from app.modules.users.models import Role, User
from tests.fakes import FakeRefreshTokenRepository, FakeSession, FakeUserRepository

SENHA = "senha-do-analista-2026"
PREFIXO = "/api/v1"


def make_user(email: str, *, role: Role = Role.ANALYST, is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(SENHA),
        full_name="Usuario de Teste",
        role=role,
        is_active=is_active,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def analyst() -> User:
    return make_user("analista@bancoexemplo.com.br", role=Role.ANALYST)


@pytest.fixture
def admin() -> User:
    return make_user("admin@bancoexemplo.com.br", role=Role.ADMIN)


@pytest.fixture
def users_repo(analyst: User, admin: User) -> FakeUserRepository:
    return FakeUserRepository([analyst, admin])


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        app_env=Environment.TEST,
        log_level="WARNING",
        log_json=True,
        jwt_secret_key="segredo-de-teste-com-tamanho-suficiente",
    )


@pytest.fixture
def app(auth_settings: Settings, users_repo: FakeUserRepository) -> Iterator[FastAPI]:
    """Aplicacao real, com os repositories substituidos por fakes.

    O grafo de dependencies, os middlewares e os handlers de erro sao os de producao —
    apenas a persistencia e trocada.
    """
    application = create_app(auth_settings)
    tokens_repo = FakeRefreshTokenRepository()

    def _service() -> AuthService:
        return AuthService(
            settings=auth_settings,
            session=FakeSession(),  # type: ignore[arg-type]
            users=users_repo,  # type: ignore[arg-type]
            refresh_tokens=tokens_repo,  # type: ignore[arg-type]
        )

    async def _session() -> Any:
        yield None

    application.dependency_overrides[get_auth_service] = _service
    # `get_current_user` resolve o usuario por aqui — e o que faz a autorizacao ser
    # exercitada de verdade, sem banco.
    application.dependency_overrides[get_user_repository] = lambda: users_repo
    application.dependency_overrides[get_session] = _session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def login(client: TestClient, user: User) -> dict[str, Any]:
    response = client.post(f"{PREFIXO}/auth/login", json={"email": user.email, "password": SENHA})
    assert response.status_code == 200, response.text
    return response.json()


def auth_header(client: TestClient, user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(client, user)['tokens']['access_token']}"}


# --- Login -----------------------------------------------------------------


def test_login_retorna_tokens_e_perfil(client: TestClient, analyst: User) -> None:
    body = login(client, analyst)

    assert body["tokens"]["token_type"] == "bearer"
    assert body["tokens"]["expires_in"] > 0
    assert body["user"]["email"] == analyst.email
    assert body["user"]["role"] == "ANALYST"


def test_login_nunca_devolve_o_hash_da_senha(client: TestClient, analyst: User) -> None:
    """Um schema de saida explicito e o que impede o hash de vazar quando um campo
    novo e adicionado ao modelo."""
    response = client.post(
        f"{PREFIXO}/auth/login", json={"email": analyst.email, "password": SENHA}
    )

    assert "password_hash" not in response.text
    assert "$argon2" not in response.text


def test_login_com_senha_errada_retorna_401(client: TestClient, analyst: User) -> None:
    response = client.post(
        f"{PREFIXO}/auth/login", json={"email": analyst.email, "password": "errada"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_com_email_inexistente_retorna_a_mesma_mensagem(
    client: TestClient, analyst: User
) -> None:
    errada = client.post(
        f"{PREFIXO}/auth/login", json={"email": analyst.email, "password": "errada"}
    )
    inexistente = client.post(
        f"{PREFIXO}/auth/login", json={"email": "ninguem@bancoexemplo.com.br", "password": SENHA}
    )

    assert errada.json()["error"] == inexistente.json()["error"] | {
        "request_id": errada.json()["error"]["request_id"]
    }


def test_login_com_email_invalido_retorna_422(client: TestClient) -> None:
    response = client.post(
        f"{PREFIXO}/auth/login", json={"email": "nao-e-email", "password": SENHA}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_conta_desativada_retorna_403(client: TestClient, users_repo: FakeUserRepository) -> None:
    inativo = make_user("inativo@bancoexemplo.com.br", is_active=False)
    users_repo._users[inativo.id] = inativo

    response = client.post(
        f"{PREFIXO}/auth/login", json={"email": inativo.email, "password": SENHA}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INACTIVE_USER"


# --- Rotas protegidas ------------------------------------------------------


def test_me_retorna_o_usuario_autenticado(client: TestClient, analyst: User) -> None:
    response = client.get(f"{PREFIXO}/auth/me", headers=auth_header(client, analyst))

    assert response.status_code == 200
    assert response.json()["email"] == analyst.email


def test_me_sem_token_retorna_401(client: TestClient) -> None:
    response = client.get(f"{PREFIXO}/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer token-invalido"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "token-sem-esquema"},
    ],
)
def test_token_invalido_retorna_401(client: TestClient, header: dict[str, str]) -> None:
    response = client.get(f"{PREFIXO}/auth/me", headers=header)

    assert response.status_code == 401


def test_usuario_desativado_apos_o_login_perde_o_acesso(client: TestClient, analyst: User) -> None:
    """O access token continua criptograficamente valido; a leitura do usuario a cada
    requisicao e o que faz a desativacao ter efeito imediato."""
    headers = auth_header(client, analyst)
    assert client.get(f"{PREFIXO}/auth/me", headers=headers).status_code == 200

    analyst.is_active = False

    assert client.get(f"{PREFIXO}/auth/me", headers=headers).status_code == 401


# --- Autorizacao por papel -------------------------------------------------


def test_analyst_nao_pode_cadastrar_usuario(client: TestClient, analyst: User) -> None:
    """Criterio de pronto da Fase 3."""
    response = client.post(
        f"{PREFIXO}/users",
        headers=auth_header(client, analyst),
        json={
            "email": "novo@bancoexemplo.com.br",
            "password": "senha-bem-comprida-1",
            "full_name": "Novo Usuario",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_admin_pode_cadastrar_usuario(client: TestClient, admin: User) -> None:
    response = client.post(
        f"{PREFIXO}/users",
        headers=auth_header(client, admin),
        json={
            "email": "novo@bancoexemplo.com.br",
            "password": "senha-bem-comprida-1",
            "full_name": "Novo Usuario",
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == "novo@bancoexemplo.com.br"
    assert response.json()["role"] == "ANALYST"


def test_cadastro_sem_autenticacao_retorna_401(client: TestClient) -> None:
    response = client.post(
        f"{PREFIXO}/users",
        json={
            "email": "novo@bancoexemplo.com.br",
            "password": "senha-bem-comprida-1",
            "full_name": "Novo Usuario",
        },
    )

    assert response.status_code == 401


def test_senha_curta_e_recusada_no_cadastro(client: TestClient, admin: User) -> None:
    response = client.post(
        f"{PREFIXO}/users",
        headers=auth_header(client, admin),
        json={
            "email": "novo@bancoexemplo.com.br",
            "password": "curta",
            "full_name": "Novo Usuario",
        },
    )

    assert response.status_code == 422
    campos = {item["field"] for item in response.json()["error"]["details"]["fields"]}
    assert "password" in campos


# --- Refresh e logout ------------------------------------------------------


def test_refresh_rotaciona_os_tokens(client: TestClient, analyst: User) -> None:
    antigos = login(client, analyst)["tokens"]

    response = client.post(
        f"{PREFIXO}/auth/refresh", json={"refresh_token": antigos["refresh_token"]}
    )

    assert response.status_code == 200
    assert response.json()["refresh_token"] != antigos["refresh_token"]


def test_refresh_reutilizado_retorna_401(client: TestClient, analyst: User) -> None:
    antigos = login(client, analyst)["tokens"]
    client.post(f"{PREFIXO}/auth/refresh", json={"refresh_token": antigos["refresh_token"]})

    response = client.post(
        f"{PREFIXO}/auth/refresh", json={"refresh_token": antigos["refresh_token"]}
    )

    assert response.status_code == 401


def test_logout_retorna_204_e_invalida_a_sessao(client: TestClient, analyst: User) -> None:
    tokens = login(client, analyst)["tokens"]

    logout = client.post(f"{PREFIXO}/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout.status_code == 204

    depois = client.post(f"{PREFIXO}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert depois.status_code == 401


def test_logout_com_token_desconhecido_tambem_retorna_204(client: TestClient) -> None:
    """Idempotente: o cliente ja descartou o cookie."""
    response = client.post(f"{PREFIXO}/auth/logout", json={"refresh_token": "nunca-existiu"})

    assert response.status_code == 204
