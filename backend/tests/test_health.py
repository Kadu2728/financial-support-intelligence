"""Health checks e contrato de infraestrutura HTTP."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.middleware import REQUEST_ID_HEADER


def test_health_retorna_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok_quando_o_banco_responde(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"


@pytest.mark.parametrize("db_fails", [True], indirect=True)
def test_readiness_retorna_503_quando_o_banco_esta_fora(client: TestClient) -> None:
    """503 tira a instancia do balanceador em vez de encaminhar requisicoes que falhariam."""
    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "unavailable"


@pytest.mark.parametrize("db_fails", [True], indirect=True)
def test_readiness_nao_vaza_detalhe_da_falha_de_banco(client: TestClient) -> None:
    """A excecao do driver pode conter a connection string, com a senha dentro."""
    response = client.get("/health/ready")

    assert "connection refused" not in response.text
    assert "password" not in response.text.lower()


def test_liveness_nao_depende_do_banco(client: TestClient) -> None:
    """Se o liveness verificasse o banco, uma oscilacao viraria restart em loop."""
    response = client.get("/health")

    assert response.status_code == 200
    assert "checks" not in response.json()


def test_request_id_e_gerado_quando_ausente(client: TestClient) -> None:
    response = client.get("/health")

    request_id = response.headers.get(REQUEST_ID_HEADER)
    assert request_id
    assert len(request_id) == 32  # uuid4().hex


def test_request_id_do_cliente_e_propagado(client: TestClient) -> None:
    """Preserva a correlacao ponta a ponta quando ha proxy upstream."""
    response = client.get("/health", headers={REQUEST_ID_HEADER: "trace-abc-123"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-abc-123"


def test_request_id_do_cliente_e_truncado(client: TestClient) -> None:
    """Entrada externa que vai para dentro de todo log precisa de limite."""
    response = client.get("/health", headers={REQUEST_ID_HEADER: "x" * 500})

    assert len(response.headers[REQUEST_ID_HEADER]) == 64


def test_headers_de_seguranca_presentes(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_hsts_ausente_fora_de_producao(client: TestClient) -> None:
    """HSTS em http://localhost trava o navegador do desenvolvedor em https."""
    response = client.get("/health")

    assert "Strict-Transport-Security" not in response.headers
