"""Contrato de erro.

O frontend decide a UI a partir de `error.code`. Se este formato quebrar, o tratamento de
erro do cliente quebra junto — por isso o contrato e testado, nao apenas documentado.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import (
    AppError,
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
)


class Payload(BaseModel):
    """Definido no nivel do modulo de proposito.

    Com `from __future__ import annotations`, a anotacao `payload: Payload` vira a string
    "Payload", e o FastAPI a resolve via `get_type_hints` no namespace do MODULO. Um modelo
    definido dentro da fixture nao e encontrado, e o FastAPI degrada silenciosamente: em vez
    de validar campo a campo, reporta um unico erro no parametro inteiro.
    """

    nome: str
    idade: int


def _assert_envelope(body: dict[str, Any], expected_code: ErrorCode) -> None:
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == expected_code.value
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], dict)
    assert error["request_id"]


@pytest.fixture
def app_com_rotas_de_erro(app: FastAPI) -> FastAPI:
    """Rotas que levantam cada classe de erro, para exercitar os handlers."""

    @app.get("/boom/not-found")
    async def _not_found() -> None:
        raise NotFoundError("Documento nao encontrado.")

    @app.get("/boom/forbidden")
    async def _forbidden() -> None:
        raise ForbiddenError()

    @app.get("/boom/conflict")
    async def _conflict() -> None:
        raise ConflictError(details={"checksum": "abc123"})

    @app.get("/boom/unhandled")
    async def _unhandled() -> None:
        raise RuntimeError("segredo=abc123 vazando na excecao")

    @app.post("/boom/validate")
    async def _validate(payload: Payload) -> Payload:
        return payload

    return app


@pytest.fixture
def error_client(app_com_rotas_de_erro: FastAPI) -> TestClient:
    return TestClient(app_com_rotas_de_erro, raise_server_exceptions=False)


def test_not_found_usa_envelope_padrao(error_client: TestClient) -> None:
    response = error_client.get("/boom/not-found")

    assert response.status_code == 404
    _assert_envelope(response.json(), ErrorCode.NOT_FOUND)
    assert response.json()["error"]["message"] == "Documento nao encontrado."


def test_forbidden_usa_mensagem_padrao_da_classe(error_client: TestClient) -> None:
    response = error_client.get("/boom/forbidden")

    assert response.status_code == 403
    _assert_envelope(response.json(), ErrorCode.FORBIDDEN)


def test_details_sao_repassados(error_client: TestClient) -> None:
    response = error_client.get("/boom/conflict")

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"checksum": "abc123"}


def test_erro_de_validacao_lista_campos(error_client: TestClient) -> None:
    response = error_client.post("/boom/validate", json={"idade": "abc"})

    assert response.status_code == 422
    body = response.json()
    _assert_envelope(body, ErrorCode.VALIDATION_ERROR)
    campos = {item["field"] for item in body["error"]["details"]["fields"]}
    assert campos == {"nome", "idade"}


def test_excecao_nao_tratada_nao_vaza_detalhe_interno(error_client: TestClient) -> None:
    """A mensagem de uma excecao inesperada pode conter dado sensivel.

    O cliente recebe texto generico; o rastro completo fica no log, correlacionado pelo
    request_id.
    """
    response = error_client.get("/boom/unhandled")

    assert response.status_code == 500
    body = response.json()
    _assert_envelope(body, ErrorCode.INTERNAL_ERROR)
    assert "segredo" not in response.text
    assert "RuntimeError" not in response.text


def test_rota_inexistente_usa_envelope_padrao(error_client: TestClient) -> None:
    """O 404 do proprio Starlette tambem precisa respeitar o contrato."""
    response = error_client.get("/rota-que-nao-existe")

    assert response.status_code == 404
    _assert_envelope(response.json(), ErrorCode.NOT_FOUND)


def test_codigos_de_erro_sao_unicos() -> None:
    """Dois codigos iguais tornariam o tratamento no frontend ambiguo."""
    valores = [code.value for code in ErrorCode]

    assert len(valores) == len(set(valores))


def test_app_error_aceita_mensagem_customizada() -> None:
    erro = AppError("mensagem propria")

    assert erro.message == "mensagem propria"
    assert erro.details == {}
