"""Health checks e contrato de infraestrutura HTTP."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.middleware import REQUEST_ID_HEADER


def test_health_retorna_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_retorna_estrutura_de_checks(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    # A partir da Fase 2 este dicionario passa a conter o check de banco.
    assert isinstance(body["checks"], dict)


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
