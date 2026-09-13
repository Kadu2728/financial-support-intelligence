"""Cliente do Gemini (embeddings e geracao).

Dois endpoints REST, chamados com httpx. Sem SDK: o `google-genai` traz dezenas de
dependencias transitivas para expor duas funcoes, e sua API publica ja mudou tres
vezes. Aqui timeout, retry e a forma exata da requisicao ficam visiveis e sob
controle — e o fake de teste implementa o mesmo Protocol sem simular um SDK.

O que este modulo garante:

- **Embeddings L2-normalizados.** Truncar para 768 dimensoes (Matryoshka) exige
  re-normalizar; sem isso a similaridade cosine degrada em silencio
  (docs/rag-design.md §1).
- **Retry so no que e transitorio.** 429, 5xx e timeout sao retentados com backoff.
  400 e 403 nao sao: repetir uma chave invalida so gasta tempo.
- **Nunca loga a chave.** A URL da API carrega a chave em query string; qualquer log
  de URL vazaria a credencial. A chave vai no header `x-goog-api-key`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import httpx
import structlog

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode

logger = structlog.get_logger(__name__)


class TaskType(StrEnum):
    """Embeddings assimetricos: documento e consulta vivem em pontos diferentes do
    espaco. Usar o mesmo tipo dos dois lados reduz recall de forma mensuravel."""

    RETRIEVAL_DOCUMENT = "RETRIEVAL_DOCUMENT"
    RETRIEVAL_QUERY = "RETRIEVAL_QUERY"


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: str | None


# --- Erros -----------------------------------------------------------------


class GeminiError(AppError):
    status_code = 502
    code = ErrorCode.UPSTREAM_UNAVAILABLE
    message = "O servico de IA nao respondeu."

    # True quando o erro veio de esgotar tentativas em condicao transitoria
    # (429, 5xx, timeout, rede). E o que autoriza cair para o modelo reserva: uma
    # chave invalida ou um schema rejeitado (400/403) falharia igual em qualquer
    # modelo, e trocar so atrasaria o erro.
    retryable: bool = False


class GeminiNotConfiguredError(GeminiError):
    status_code = 503
    message = "GEMINI_API_KEY nao configurada. O copilot e a indexacao estao desativados."


class GeminiTimeoutError(GeminiError):
    status_code = 504
    code = ErrorCode.GENERATION_TIMEOUT
    message = "O servico de IA demorou demais para responder."


class GeminiRateLimitedError(GeminiError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    message = "Limite de uso do servico de IA atingido. Tente novamente em instantes."


class GeminiBadResponseError(GeminiError):
    message = "O servico de IA devolveu uma resposta inesperada."


# --- Contrato --------------------------------------------------------------


@runtime_checkable
class EmbeddingClient(Protocol):
    @property
    def embedding_model(self) -> str: ...

    async def embed(self, textos: list[str], *, task_type: TaskType) -> list[list[float]]: ...


@runtime_checkable
class GenerationClient(Protocol):
    @property
    def generation_model(self) -> str: ...

    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict[str, Any],
        temperature: float,
    ) -> GenerationResult: ...


# --- Implementacao ----------------------------------------------------------

_RETENTAVEIS = frozenset({429, 500, 502, 503, 504})
_MAX_TENTATIVAS = 4
# Com modelo reserva configurado, o principal recebe menos tentativas: cada 503 de
# "high demand" leva ~20 s para chegar, e o reserva costuma responder em segundos.
_TENTATIVAS_ANTES_DA_RESERVA = 2
_BACKOFF_BASE_S = 1.0


class GeminiClient:
    """Implementa `EmbeddingClient` e `GenerationClient` sobre a API REST."""

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
        dimensoes: int = 768,
    ) -> None:
        if not settings.gemini_configured:
            raise GeminiNotConfiguredError

        self._settings = settings
        self._dimensoes = dimensoes
        self._http = http or httpx.AsyncClient(
            base_url=settings.gemini_base_url,
            timeout=httpx.Timeout(settings.gemini_timeout_seconds, connect=10.0),
            headers={"x-goog-api-key": settings.gemini_api_key.get_secret_value()},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def embedding_model(self) -> str:
        return self._settings.gemini_embedding_model

    @property
    def generation_model(self) -> str:
        return self._settings.gemini_generation_model

    # --- Embeddings ---------------------------------------------------------

    async def embed(self, textos: list[str], *, task_type: TaskType) -> list[list[float]]:
        if not textos:
            return []

        lote = self._settings.gemini_embedding_batch_size
        vetores: list[list[float]] = []
        for inicio in range(0, len(textos), lote):
            vetores.extend(await self._embed_lote(textos[inicio : inicio + lote], task_type))
        return vetores

    async def _embed_lote(self, textos: list[str], task_type: TaskType) -> list[list[float]]:
        modelo = f"models/{self.embedding_model}"
        corpo = {
            "requests": [
                {
                    "model": modelo,
                    "content": {"parts": [{"text": texto}]},
                    "taskType": task_type.value,
                    "outputDimensionality": self._dimensoes,
                }
                for texto in textos
            ]
        }
        dados = await self._post(f"/{modelo}:batchEmbedContents", corpo)

        try:
            brutos = [item["values"] for item in dados["embeddings"]]
        except (KeyError, TypeError) as exc:
            raise GeminiBadResponseError("Resposta de embedding sem o campo esperado.") from exc

        if len(brutos) != len(textos):
            raise GeminiBadResponseError(
                f"Esperados {len(textos)} embeddings, recebidos {len(brutos)}."
            )

        return [_normalizar_l2(_validar_dimensao(v, self._dimensoes)) for v in brutos]

    # --- Geracao ------------------------------------------------------------

    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict[str, Any],
        temperature: float,
    ) -> GenerationResult:
        corpo = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
            },
            # Nenhuma tool: sem tools, uma injecao de prompt no conteudo recuperado
            # nao tem para onde escalar (docs/rag-design.md §8).
        }

        # Cadeia de modelos. A sobrecarga do Gemini ("high demand", 503) e POR
        # MODELO e cada 503 demora ~20 s para chegar; retentar o mesmo modelo quatro
        # vezes custava 80 s para entregar um erro. Na sobrecarga, o modelo
        # reserva responde em segundos. O modelo que de fato respondeu vai em
        # `GenerationResult.model` e, dali, para `queries.model` — e o que permite
        # comparar qualidade por modelo depois.
        modelos = [self.generation_model]
        reserva = self._settings.gemini_generation_fallback_model
        if reserva and reserva != self.generation_model:
            modelos.append(reserva)

        dados: dict[str, Any] | None = None
        modelo_usado = modelos[0]
        for indice, modelo in enumerate(modelos):
            e_ultimo = indice == len(modelos) - 1
            try:
                dados = await self._post(
                    f"/models/{modelo}:generateContent",
                    corpo,
                    # Uma tentativa extra so quando nao ha para onde cair.
                    tentativas=_MAX_TENTATIVAS if e_ultimo else _TENTATIVAS_ANTES_DA_RESERVA,
                )
                modelo_usado = modelo
                break
            except GeminiError as exc:
                if e_ultimo or not exc.retryable:
                    raise
                logger.warning(
                    "gemini_generation_fallback",
                    from_model=modelo,
                    to_model=modelos[indice + 1],
                    reason=exc.code.value,
                )
        assert dados is not None  # o loop retorna dados ou levanta

        candidatos = dados.get("candidates") or []
        if not candidatos:
            # Bloqueio por safety filter chega assim: sem candidato, com
            # `promptFeedback.blockReason`.
            motivo = (dados.get("promptFeedback") or {}).get("blockReason")
            raise GeminiBadResponseError(
                "O modelo nao produziu resposta." + (f" Motivo: {motivo}." if motivo else "")
            )

        candidato = candidatos[0]
        partes = (candidato.get("content") or {}).get("parts") or []
        texto = "".join(str(p.get("text", "")) for p in partes)
        if not texto.strip():
            raise GeminiBadResponseError("O modelo devolveu conteudo vazio.")

        uso = dados.get("usageMetadata") or {}
        return GenerationResult(
            text=texto,
            model=modelo_usado,
            prompt_tokens=_inteiro(uso.get("promptTokenCount")),
            completion_tokens=_inteiro(uso.get("candidatesTokenCount")),
            finish_reason=candidato.get("finishReason"),
        )

    # --- Transporte ---------------------------------------------------------

    async def _post(
        self, caminho: str, corpo: dict[str, Any], *, tentativas: int = _MAX_TENTATIVAS
    ) -> dict[str, Any]:
        ultimo_erro: GeminiError | None = None

        for tentativa in range(1, tentativas + 1):
            try:
                resposta = await self._http.post(caminho, json=corpo)
            except httpx.TimeoutException as exc:
                ultimo_erro = GeminiTimeoutError()
                logger.warning("gemini_timeout", path=caminho, attempt=tentativa)
                ultimo_erro.__cause__ = exc
            except httpx.HTTPError as exc:
                ultimo_erro = GeminiError("Falha de rede ao chamar o servico de IA.")
                ultimo_erro.__cause__ = exc
                logger.warning(
                    "gemini_network_error",
                    path=caminho,
                    attempt=tentativa,
                    error_type=type(exc).__name__,
                )
            else:
                if resposta.status_code < 400:
                    try:
                        return dict(resposta.json())
                    except (json.JSONDecodeError, ValueError, TypeError) as exc:
                        raise GeminiBadResponseError from exc

                ultimo_erro = _erro_http(resposta)
                if resposta.status_code not in _RETENTAVEIS:
                    raise ultimo_erro

                logger.warning(
                    "gemini_retryable_status",
                    path=caminho,
                    status=resposta.status_code,
                    attempt=tentativa,
                )

            if tentativa < tentativas:
                # Backoff exponencial: 1s, 2s, 4s. Sem jitter de proposito — um so
                # processo, sem rebanho para sincronizar.
                await asyncio.sleep(_BACKOFF_BASE_S * (2 ** (tentativa - 1)))

        assert ultimo_erro is not None  # invariante do loop
        ultimo_erro.retryable = True
        raise ultimo_erro


def _erro_http(resposta: httpx.Response) -> GeminiError:
    # Nunca repassar o corpo inteiro ao usuario: pode conter detalhes internos do
    # Google. O log recebe o status; a mensagem, so o necessario.
    detalhe = ""
    with contextlib.suppress(json.JSONDecodeError, ValueError, AttributeError, TypeError):
        detalhe = str(resposta.json().get("error", {}).get("message", ""))[:200]

    logger.error("gemini_http_error", status=resposta.status_code, detail=detalhe)

    if resposta.status_code == 429:
        return GeminiRateLimitedError()
    if resposta.status_code in (401, 403):
        return GeminiError("Chave do Gemini invalida ou sem permissao.")
    if resposta.status_code == 400:
        return GeminiBadResponseError("O servico de IA rejeitou a requisicao.")
    return GeminiError()


def _validar_dimensao(vetor: object, esperado: int) -> list[float]:
    if not isinstance(vetor, list) or len(vetor) != esperado:
        tamanho = len(vetor) if isinstance(vetor, list) else "?"
        raise GeminiBadResponseError(f"Embedding com {tamanho} dimensoes; esperado {esperado}.")
    return [float(x) for x in vetor]


def _normalizar_l2(vetor: list[float]) -> list[float]:
    norma = math.sqrt(sum(x * x for x in vetor))
    if norma == 0:
        return vetor
    return [x / norma for x in vetor]


def _inteiro(valor: object) -> int | None:
    return int(valor) if isinstance(valor, int | float) else None
