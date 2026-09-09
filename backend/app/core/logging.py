"""Logging estruturado.

Em producao: JSON, uma linha por evento, agregavel.
Em desenvolvimento: console colorido e legivel.

Todo log carrega `request_id`, injetado por contexto (ver `middleware.py`), o que permite
reconstruir uma requisicao inteira a partir de um unico identificador — inclusive as linhas
emitidas em camadas que nao conhecem HTTP.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import Settings

# Campos que nunca devem chegar ao log, em nenhum ambiente.
_REDACTED_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "gemini_api_key",
        "secret_key",
    }
)
_REDACTED = "[REDACTED]"


def _redact(
    _logger: object, _name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Rede de seguranca contra vazamento acidental de credencial em log.

    A primeira linha de defesa continua sendo nao passar o campo. Esta e a segunda.
    """
    for key in list(event_dict):
        if key.lower() in _REDACTED_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level.upper(),
    )

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact,
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
