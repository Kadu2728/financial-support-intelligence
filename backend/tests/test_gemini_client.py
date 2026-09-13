"""Cliente do Gemini contra um transporte HTTP falso.

O que se testa aqui e o CONTRATO com a API — forma da requisicao, normalizacao,
retry — e nao o Gemini em si. `httpx.MockTransport` permite responder cada chamada
sem rede e sem monkeypatch.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable

import httpx
import pytest

from app.core.config import Settings
from app.integrations.gemini.client import (
    GeminiBadResponseError,
    GeminiClient,
    GeminiError,
    GeminiNotConfiguredError,
    GeminiRateLimitedError,
    GeminiTimeoutError,
    TaskType,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gemini_api_key="chave-de-teste",
        gemini_embedding_batch_size=2,
        jwt_secret_key="segredo-de-teste-com-tamanho-suficiente",
    )


def build_client(
    settings: Settings, handler: Callable[[httpx.Request], httpx.Response]
) -> GeminiClient:
    http = httpx.AsyncClient(
        base_url=settings.gemini_base_url,
        transport=httpx.MockTransport(handler),
        headers={"x-goog-api-key": settings.gemini_api_key.get_secret_value()},
    )
    return GeminiClient(settings, http=http)


def embeddings_response(request: httpx.Request, *, escala: float = 3.0) -> httpx.Response:
    corpo = json.loads(request.content)
    n = len(corpo["requests"])
    # Vetores nao normalizados de proposito: o cliente precisa normalizar.
    return httpx.Response(
        200, json={"embeddings": [{"values": [escala] + [0.0] * 767} for _ in range(n)]}
    )


# --- Configuracao ------------------------------------------------------------


def test_sem_chave_recusa_construir() -> None:
    settings = Settings(jwt_secret_key="segredo-de-teste-com-tamanho-suficiente")
    assert settings.gemini_configured is False
    with pytest.raises(GeminiNotConfiguredError):
        GeminiClient(settings)


def test_chave_obrigatoria_em_producao() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        Settings(
            app_env="production",
            jwt_secret_key="segredo-de-producao-com-tamanho-suficiente-mesmo",
        )


# --- Embeddings ---------------------------------------------------------------


async def test_embed_envia_task_type_dimensao_e_chave_no_header(settings: Settings) -> None:
    capturadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturadas.append(request)
        return embeddings_response(request)

    cliente = build_client(settings, handler)
    await cliente.embed(["a"], task_type=TaskType.RETRIEVAL_QUERY)

    req = capturadas[0]
    corpo = json.loads(req.content)
    assert req.url.path.endswith("models/gemini-embedding-001:batchEmbedContents")
    assert req.headers["x-goog-api-key"] == "chave-de-teste"
    # A chave NUNCA vai na URL: qualquer log de URL a vazaria.
    assert "chave-de-teste" not in str(req.url)
    pedido = corpo["requests"][0]
    assert pedido["taskType"] == "RETRIEVAL_QUERY"
    assert pedido["outputDimensionality"] == 768
    assert pedido["model"] == "models/gemini-embedding-001"


async def test_embed_normaliza_l2(settings: Settings) -> None:
    cliente = build_client(settings, embeddings_response)
    [vetor] = await cliente.embed(["x"], task_type=TaskType.RETRIEVAL_DOCUMENT)

    assert len(vetor) == 768
    assert math.isclose(math.sqrt(sum(v * v for v in vetor)), 1.0, abs_tol=1e-9)


async def test_embed_divide_em_lotes(settings: Settings) -> None:
    tamanhos: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tamanhos.append(len(json.loads(request.content)["requests"]))
        return embeddings_response(request)

    cliente = build_client(settings, handler)
    vetores = await cliente.embed(["1", "2", "3", "4", "5"], task_type=TaskType.RETRIEVAL_DOCUMENT)

    assert tamanhos == [2, 2, 1]
    assert len(vetores) == 5


async def test_embed_lista_vazia_nao_chama_api(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nao deveria chamar")

    cliente = build_client(settings, handler)
    assert await cliente.embed([], task_type=TaskType.RETRIEVAL_DOCUMENT) == []


async def test_embed_contagem_diferente_e_erro(settings: Settings) -> None:
    """Um desalinhamento gravaria o vetor de um chunk no registro de outro."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [{"values": [1.0] * 768}]})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiBadResponseError, match="Esperados 2"):
        await cliente.embed(["a", "b"], task_type=TaskType.RETRIEVAL_DOCUMENT)


async def test_embed_dimensao_errada_e_erro(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [{"values": [1.0] * 10}]})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiBadResponseError, match="10 dimensoes"):
        await cliente.embed(["a"], task_type=TaskType.RETRIEVAL_DOCUMENT)


# --- Retry --------------------------------------------------------------------


async def test_retenta_em_503_e_sucede(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.integrations.gemini.client as modulo

    esperas: list[float] = []

    async def sem_espera(segundos: float) -> None:
        esperas.append(segundos)

    monkeypatch.setattr(modulo.asyncio, "sleep", sem_espera)

    tentativas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal tentativas
        tentativas += 1
        if tentativas < 3:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return embeddings_response(request)

    cliente = build_client(settings, handler)
    vetores = await cliente.embed(["a"], task_type=TaskType.RETRIEVAL_DOCUMENT)

    assert len(vetores) == 1
    assert tentativas == 3
    assert esperas == [1.0, 2.0]  # backoff exponencial


async def test_nao_retenta_em_400(settings: Settings) -> None:
    tentativas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal tentativas
        tentativas += 1
        return httpx.Response(400, json={"error": {"message": "bad"}})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiBadResponseError):
        await cliente.embed(["a"], task_type=TaskType.RETRIEVAL_DOCUMENT)
    assert tentativas == 1


async def test_403_e_erro_de_chave_sem_retry(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "forbidden"}})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiError, match="Chave"):
        await cliente.embed(["a"], task_type=TaskType.RETRIEVAL_DOCUMENT)


async def test_429_esgota_e_levanta_rate_limited(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.integrations.gemini.client as modulo

    async def sem_espera(segundos: float) -> None:
        pass

    monkeypatch.setattr(modulo.asyncio, "sleep", sem_espera)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiRateLimitedError):
        await cliente.embed(["a"], task_type=TaskType.RETRIEVAL_DOCUMENT)


async def test_timeout_vira_erro_proprio(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.integrations.gemini.client as modulo

    async def sem_espera(segundos: float) -> None:
        pass

    monkeypatch.setattr(modulo.asyncio, "sleep", sem_espera)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiTimeoutError):
        await cliente.embed(["a"], task_type=TaskType.RETRIEVAL_DOCUMENT)


# --- Geracao -----------------------------------------------------------------


async def test_generate_json_envia_schema_sem_tools(settings: Settings) -> None:
    capturadas: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturadas.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": '{"answer": "ok"}'}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 8},
            },
        )

    cliente = build_client(settings, handler)
    resultado = await cliente.generate_json(
        system="sistema",
        user="pergunta",
        response_schema={"type": "OBJECT"},
        temperature=0.2,
    )

    corpo = capturadas[0]
    assert corpo["systemInstruction"] == {"parts": [{"text": "sistema"}]}
    assert corpo["generationConfig"]["responseMimeType"] == "application/json"
    assert corpo["generationConfig"]["temperature"] == 0.2
    # Sem tools, uma injecao no contexto nao tem para onde escalar.
    assert "tools" not in corpo
    assert resultado.text == '{"answer": "ok"}'
    assert resultado.prompt_tokens == 120
    assert resultado.completion_tokens == 8
    assert resultado.model == "gemini-3.8-flash"


async def test_generate_sem_candidato_expoe_motivo_do_bloqueio(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}
        )

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiBadResponseError, match="SAFETY"):
        await cliente.generate_json(system="s", user="u", response_schema={}, temperature=0.0)


async def test_generate_conteudo_vazio_e_erro(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiBadResponseError, match="vazio"):
        await cliente.generate_json(system="s", user="u", response_schema={}, temperature=0.0)


# --- Modelo reserva -----------------------------------------------------------------


def _resposta_ok(texto: str = '{"answer": "ok"}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": [{"text": texto}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3},
        },
    )


def _sem_espera(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.integrations.gemini.client as modulo

    async def dormir(segundos: float) -> None:
        pass

    monkeypatch.setattr(modulo.asyncio, "sleep", dormir)


async def test_sobrecarga_do_principal_cai_para_o_reserva(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cada 503 de "high demand" leva ~20 s para chegar. Quatro tentativas no mesmo
    modelo custavam 80 s para entregar um erro; o reserva responde em segundos."""
    _sem_espera(monkeypatch)
    chamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.url.path.rsplit("/", 1)[-1].split(":")[0])
        if "3.8-flash" in request.url.path:
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return _resposta_ok()

    cliente = build_client(settings, handler)
    resultado = await cliente.generate_json(
        system="s", user="u", response_schema={}, temperature=0.0
    )

    # Duas tentativas no principal, depois o reserva na primeira.
    assert chamadas == ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]
    # O modelo que respondeu e o que vai para `queries.model`, nao o configurado.
    assert resultado.model == "gemini-3.5-flash-lite"


async def test_reserva_recebe_todas_as_tentativas_quando_tambem_falha(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sem_espera(monkeypatch)
    chamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.url.path.rsplit("/", 1)[-1].split(":")[0])
        return httpx.Response(503, json={"error": {"message": "high demand"}})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiError) as erro:
        await cliente.generate_json(system="s", user="u", response_schema={}, temperature=0.0)

    assert chamadas.count("gemini-3.8-flash") == 2
    assert chamadas.count("gemini-3.5-flash-lite") == 4
    assert erro.value.retryable is True


async def test_erro_definitivo_nao_cai_para_o_reserva(settings: Settings) -> None:
    """400 (schema rejeitado) ou 403 (chave) falhariam igual em qualquer modelo."""
    chamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.url.path)
        return httpx.Response(400, json={"error": {"message": "bad schema"}})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiBadResponseError) as erro:
        await cliente.generate_json(system="s", user="u", response_schema={}, temperature=0.0)

    assert len(chamadas) == 1
    assert "3.8-flash" in chamadas[0]
    assert erro.value.retryable is False


async def test_sem_reserva_configurado_o_principal_recebe_todas_as_tentativas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sem_espera(monkeypatch)
    settings = Settings(
        gemini_api_key="chave-de-teste",
        gemini_generation_fallback_model="",
        jwt_secret_key="segredo-de-teste-com-tamanho-suficiente",
    )
    tentativas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal tentativas
        tentativas += 1
        return httpx.Response(503, json={"error": {"message": "high demand"}})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiError):
        await cliente.generate_json(system="s", user="u", response_schema={}, temperature=0.0)
    assert tentativas == 4


async def test_embeddings_nao_usam_reserva(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Embeddings de outro modelo viveriam em outro espaco vetorial: nunca cair."""
    _sem_espera(monkeypatch)
    caminhos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        caminhos.append(request.url.path)
        return httpx.Response(503, json={"error": {"message": "high demand"}})

    cliente = build_client(settings, handler)
    with pytest.raises(GeminiError):
        await cliente.embed(["a"], task_type=TaskType.RETRIEVAL_DOCUMENT)
    assert len(caminhos) == 4
    assert all("gemini-embedding-001" in c for c in caminhos)
