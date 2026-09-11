"""Contrato de extracao de texto.

O extrator devolve **blocos tipados**, nao uma string.

DOCX e Markdown sabem o que e titulo — o primeiro por estilo, o segundo por `#`.
Concatenar tudo numa string jogaria essa informacao fora e obrigaria o chunker a
re-inferir por heuristica algo que ja era conhecido com certeza. PDF e TXT nao tem
essa marcacao, e para eles a deteccao por numeracao entra como fallback.

Cada extrator entrega o que o formato sabe. O normalizador uniformiza o resto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from app.core.errors import AppError, ErrorCode


class TipoBloco(StrEnum):
    TITULO = "TITULO"
    PARAGRAFO = "PARAGRAFO"


@dataclass(frozen=True, slots=True)
class Bloco:
    texto: str
    tipo: TipoBloco = TipoBloco.PARAGRAFO
    # Preenchido apenas quando o FORMATO declara o nivel (DOCX, Markdown). `None` em
    # PDF e TXT, onde a hierarquia so pode ser inferida da numeracao.
    nivel: int | None = None
    pagina: int | None = None


@dataclass(frozen=True, slots=True)
class TextoExtraido:
    blocos: list[Bloco]
    total_paginas: int | None = None
    metadados: dict[str, str] = field(default_factory=dict)

    @property
    def vazio(self) -> bool:
        return not any(b.texto.strip() for b in self.blocos)


class ExtractionError(AppError):
    status_code = 422
    code = ErrorCode.EXTRACTION_FAILED
    message = "Nao foi possivel extrair o texto do documento."


class NoTextLayerError(AppError):
    """PDF sem camada de texto — tipicamente um documento escaneado.

    Erro proprio, e nao ExtractionError generico, porque a acao do administrador e
    diferente: nao adianta reenviar o mesmo arquivo. Ele precisa de um PDF pesquisavel
    ou de OCR, que esta fora do escopo da v1.
    """

    status_code = 422
    code = ErrorCode.NO_TEXT_LAYER
    message = (
        "O PDF nao contem texto selecionavel. Documentos digitalizados exigem OCR, "
        "ainda nao suportado. Envie uma versao pesquisavel do arquivo."
    )


@runtime_checkable
class TextExtractor(Protocol):
    def extrair(self, conteudo: bytes) -> TextoExtraido: ...
