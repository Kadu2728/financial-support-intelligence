from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Environment, Settings
from app.main import create_app


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


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False faz o TestClient exercitar o handler global de
    # excecoes em vez de propagar o erro — sem isso, o contrato de erro 500 nao e testavel.
    return TestClient(app, raise_server_exceptions=False)
