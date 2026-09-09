"""Contrato de erro unico da API.

Todo erro sai no mesmo formato, com um `code` estavel que o frontend usa para decidir a UI:

    {"error": {"code": "...", "message": "...", "details": {}, "request_id": "..."}}

`code` e contrato — mudar um valor quebra o frontend. `message` e texto humano em pt-BR e pode
ser reescrito livremente.

Nenhum endpoint monta resposta de erro a mao: levanta a excecao de dominio e os handlers
registrados aqui fazem a traducao. Isso e o que mantem o formato consistente sem disciplina manual.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


class ErrorCode(StrEnum):
    """Codigos de erro estaveis. Adicionar e seguro; renomear e breaking change."""

    # Genericos
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"

    # Autenticacao e autorizacao (Fase 3)
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # noqa: S105 - codigo de erro, nao credencial
    TOKEN_INVALID = "TOKEN_INVALID"  # noqa: S105 - codigo de erro, nao credencial
    FORBIDDEN = "FORBIDDEN"
    INACTIVE_USER = "INACTIVE_USER"

    # Documentos e ingestao (Fases 4-5)
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    NO_TEXT_LAYER = "NO_TEXT_LAYER"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    DOCUMENT_NOT_READY = "DOCUMENT_NOT_READY"

    # RAG (Fase 7)
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    GENERATION_FAILED = "GENERATION_FAILED"
    GENERATION_TIMEOUT = "GENERATION_TIMEOUT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"


class AppError(Exception):
    """Raiz de toda excecao de dominio.

    Carrega o status HTTP junto do codigo porque a traducao dominio -> HTTP e uma propriedade
    do erro, nao de quem o captura. Isso evita a mesma condicao virar 400 num endpoint e 422
    em outro.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str = "Erro interno."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = ErrorCode.NOT_FOUND
    message = "Recurso nao encontrado."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = ErrorCode.CONFLICT
    message = "O recurso ja existe ou esta em estado conflitante."


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = ErrorCode.VALIDATION_ERROR
    message = "Dados invalidos."


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = ErrorCode.TOKEN_INVALID
    message = "Autenticacao necessaria."


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = ErrorCode.FORBIDDEN
    message = "Voce nao tem permissao para executar esta acao."


class UpstreamError(AppError):
    """Falha em servico externo (Gemini, storage). 502: o erro nao e do cliente."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = ErrorCode.UPSTREAM_UNAVAILABLE
    message = "Servico externo indisponivel no momento."


def _envelope(
    code: str,
    message: str,
    request_id: str | None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        # 5xx e falha nossa e merece stacktrace; 4xx e comportamento esperado do cliente.
        log = logger.error if exc.status_code >= 500 else logger.info
        log(
            "app_error",
            code=exc.code.value,
            status_code=exc.status_code,
            path=request.url.path,
            exc_info=exc.status_code >= 500,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code.value, exc.message, request_id, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Traduz o 422 do FastAPI para o envelope padrao.

        Sem isso, erros de validacao sairiam num formato diferente de todo o resto da API.
        """
        fields = [
            {
                "field": ".".join(str(part) for part in err["loc"][1:]) or "body",
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope(
                ErrorCode.VALIDATION_ERROR.value,
                "Dados invalidos.",
                getattr(request.state, "request_id", None),
                {"fields": fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = (
            ErrorCode.NOT_FOUND
            if exc.status_code == status.HTTP_404_NOT_FOUND
            else ErrorCode.INTERNAL_ERROR
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                code.value,
                str(exc.detail),
                getattr(request.state, "request_id", None),
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Ultima barreira.

        A mensagem exposta e generica de proposito: detalhe de excecao nao tratada pode
        conter estrutura interna, query ou dado sensivel. O `request_id` correlaciona com o
        log completo, que tem tudo.
        """
        logger.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                ErrorCode.INTERNAL_ERROR.value,
                "Erro interno. Se persistir, informe o identificador da requisicao.",
                getattr(request.state, "request_id", None),
            ),
        )
