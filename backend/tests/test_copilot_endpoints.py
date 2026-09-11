"""Contrato HTTP do copilot: autenticacao, 503 sem chave, rate limit, validacao.

O RAG em si e testado no service (tests/integration/test_rag_flow.py). Aqui o
`RagService` e substituido por um fake que devolve uma resposta pronta — o que
se exercita e a borda: dependencies, codigos de erro e o limiter.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Environment, Settings
from app.core.dependencies import get_session
from app.main import create_app
from app.modules.auth.dependencies import get_auth_service, get_user_repository
from app.modules.auth.service import AuthService
from app.modules.rag.router import get_rag_service
from app.modules.users.models import Role
from tests.fakes import FakeRefreshTokenRepository, FakeSession, FakeUserRepository
from tests.test_auth_endpoints import PREFIXO, auth_header, make_user


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env=Environment.TEST,
        log_level="WARNING",
        jwt_secret_key="segredo-de-teste-com-tamanho-suficiente",
        rate_limit_copilot_per_minute=2,
        worker_enabled=False,
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    application = create_app(settings)
    analyst = make_user("ana@bancoexemplo.com.br", role=Role.ANALYST)
    users_repo = FakeUserRepository([analyst])
    application.state.analyst = analyst

    def _auth() -> AuthService:
        return AuthService(
            settings=settings,
            session=FakeSession(),  # type: ignore[arg-type]
            users=users_repo,  # type: ignore[arg-type]
            refresh_tokens=FakeRefreshTokenRepository(),  # type: ignore[arg-type]
        )

    async def _session() -> Any:
        yield None

    application.dependency_overrides[get_auth_service] = _auth
    application.dependency_overrides[get_user_repository] = lambda: users_repo
    application.dependency_overrides[get_session] = _session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_copilot_exige_autenticacao(client: TestClient) -> None:
    response = client.post(f"{PREFIXO}/copilot/query", json={"question": "Qual o prazo?"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


def test_sem_chave_do_gemini_responde_503_com_causa(client: TestClient, app: FastAPI) -> None:
    """A aplicacao sobe sem a chave; o copilot diz por que nao funciona."""
    headers = auth_header(client, app.state.analyst)
    response = client.post(
        f"{PREFIXO}/copilot/query", json={"question": "Qual o prazo?"}, headers=headers
    )
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["error"]["message"]


def test_pergunta_curta_demais_e_422(client: TestClient, app: FastAPI) -> None:
    headers = auth_header(client, app.state.analyst)
    response = client.post(f"{PREFIXO}/copilot/query", json={"question": "oi"}, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_rate_limit_por_usuario(client: TestClient, app: FastAPI) -> None:
    class _RagFalso:
        async def answer(self, pergunta: str, *, user_id: uuid.UUID) -> Any:
            raise AssertionError("nao deve chegar ao service depois do limite")

    # O limiter roda ANTES do service: mesmo com o service quebrado, as duas
    # primeiras passam por ele (e falham la), a terceira e barrada com 429.
    app.dependency_overrides[get_rag_service] = lambda: _RagFalso()
    headers = auth_header(client, app.state.analyst)
    codigos = [
        client.post(
            f"{PREFIXO}/copilot/query", json={"question": "Qual o prazo?"}, headers=headers
        ).status_code
        for _ in range(3)
    ]
    assert codigos[:2] == [500, 500]
    assert codigos[2] == 429
    corpo = client.post(
        f"{PREFIXO}/copilot/query", json={"question": "Qual o prazo?"}, headers=headers
    ).json()
    assert corpo["error"]["code"] == "RATE_LIMITED"
    assert corpo["error"]["details"]["retry_after_seconds"] >= 1


def test_rotas_novas_estao_no_openapi(app: FastAPI) -> None:
    caminhos = set(app.openapi()["paths"])
    assert f"{PREFIXO}/copilot/query" in caminhos
    assert f"{PREFIXO}/search" in caminhos
    assert f"{PREFIXO}/queries" in caminhos
    assert f"{PREFIXO}/queries/{{query_id}}" in caminhos
    assert f"{PREFIXO}/queries/{{query_id}}/feedback" in caminhos
