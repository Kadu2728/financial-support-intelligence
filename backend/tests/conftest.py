from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Environment, Settings
from app.core.dependencies import get_session
from app.main import create_app


@pytest.fixture(autouse=True)
def _sem_gemini_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    """A suite nunca usa a chave real do `.env` do desenvolvedor.

    Variavel de ambiente tem precedencia sobre o arquivo `.env` no
    pydantic-settings; vazia, deixa `gemini_configured` falso. Quem precisa de
    chave passa `gemini_api_key=...` ao construir `Settings` — argumento vence os
    dois. O worker tambem fica desligado: nenhum teste deve disparar ingestao real.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("WORKER_ENABLED", "false")


@pytest.fixture
def settings() -> Settings:
    """Configuracao isolada por teste.

    Construida explicitamente em vez de lida do ambiente: um `.env` na maquina do
    desenvolvedor nao pode alterar o resultado da suite.
    """
    return Settings(
        app_env=Environment.TEST,
        log_level="WARNING",
        log_json=True,
        cors_origins=["http://localhost:3000"],
    )


class FakeSession:
    """Sessao de banco falsa para os testes que nao precisam de banco real.

    Cobre o comportamento observavel de que os endpoints dependem — `execute` funciona
    ou levanta. Testes que exercitam SQL de verdade sao marcados `integration` e rodam
    contra o Neon (Fase 2+, quando a credencial estiver disponivel).
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.executed: list[Any] = []

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if self.fail:
            raise ConnectionError("connection refused")
        self.executed.append(statement)
        return None


@pytest.fixture
def db_fails(request: pytest.FixtureRequest) -> bool:
    """Simula queda do banco via `@pytest.mark.parametrize(..., indirect=True)`."""
    return bool(getattr(request, "param", False))


@pytest.fixture
def app(settings: Settings, db_fails: bool) -> Iterator[FastAPI]:
    application = create_app(settings)

    async def _override_session() -> Any:
        yield FakeSession(fail=db_fails)

    application.dependency_overrides[get_session] = _override_session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False faz o TestClient exercitar o handler global de
    # excecoes em vez de propagar o erro — sem isso, o contrato de erro 500 nao e testavel.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
