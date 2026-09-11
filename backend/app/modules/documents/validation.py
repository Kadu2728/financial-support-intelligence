"""Validacao de arquivos enviados.

Este e o ponto por onde conteudo nao confiavel entra no sistema. Duas regras guiam o
modulo:

1. **A extensao e o Content-Type nao valem nada.** Ambos sao escolhidos por quem envia.
   O tipo real vem da assinatura dos primeiros bytes.

2. **O limite de tamanho e aplicado DURANTE a leitura.** Verificar depois significa que
   o arquivo ja foi inteiramente carregado — o que e exatamente o que o limite existe
   para impedir.

A validacao de assinatura e feita aqui em vez de por `python-magic` porque a libmagic
exige um binario nativo, dificil de instalar no Windows. Os formatos suportados sao
poucos e suas assinaturas sao estaveis ha decadas.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from typing import BinaryIO

from app.core.errors import AppError, ErrorCode


class DocumentFormat(StrEnum):
    PDF = "PDF"
    DOCX = "DOCX"
    MARKDOWN = "MARKDOWN"
    TEXT = "TEXT"


MIME_POR_FORMATO = {
    DocumentFormat.PDF: "application/pdf",
    DocumentFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DocumentFormat.MARKDOWN: "text/markdown",
    DocumentFormat.TEXT: "text/plain",
}

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
_CHUNK = 64 * 1024

# Bytes lidos para identificar o formato. Suficiente para qualquer assinatura conhecida
# e para julgar se o conteudo e texto valido.
_AMOSTRA = 8192


class FileTooLargeError(AppError):
    status_code = 413
    code = ErrorCode.FILE_TOO_LARGE
    message = f"Arquivo acima do limite de {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = ErrorCode.UNSUPPORTED_FILE_TYPE
    message = "Formato nao suportado. Envie PDF, DOCX, Markdown ou texto."


class EmptyFileError(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_ERROR
    message = "O arquivo esta vazio."


@dataclass(frozen=True, slots=True)
class ValidatedFile:
    content: bytes
    size_bytes: int
    checksum_sha256: str
    formato: DocumentFormat

    @property
    def mime_type(self) -> str:
        return MIME_POR_FORMATO[self.formato]


def read_and_validate(stream: BinaryIO, *, filename: str) -> ValidatedFile:
    """Le o arquivo aplicando o limite de tamanho e identifica o formato real.

    O checksum sai da mesma passagem: ler duas vezes para hashear seria desperdicio, e
    ele e o que detecta re-upload identico antes de gastar chamadas de embedding.
    """
    digest = hashlib.sha256()
    partes: list[bytes] = []
    total = 0

    while pedaco := stream.read(_CHUNK):
        total += len(pedaco)
        if total > MAX_FILE_SIZE_BYTES:
            # Aborta no pedaco que ultrapassa, sem ler o restante.
            raise FileTooLargeError
        digest.update(pedaco)
        partes.append(pedaco)

    if total == 0:
        raise EmptyFileError

    conteudo = b"".join(partes)
    formato = detect_format(conteudo, filename=filename)

    return ValidatedFile(
        content=conteudo,
        size_bytes=total,
        checksum_sha256=digest.hexdigest(),
        formato=formato,
    )


def detect_format(conteudo: bytes, *, filename: str) -> DocumentFormat:
    """Identifica o formato pelo conteudo. A extensao so desempata texto de markdown."""
    amostra = conteudo[:_AMOSTRA]

    # PDF: "%PDF-" nos primeiros bytes.
    if conteudo.startswith(b"%PDF-"):
        return DocumentFormat.PDF

    # DOCX e um ZIP (assinatura PK\x03\x04). Como .xlsx, .pptx e .jar tambem sao,
    # e preciso olhar dentro: so o DOCX tem `word/document.xml`.
    if conteudo.startswith(b"PK\x03\x04"):
        if _e_docx(conteudo):
            return DocumentFormat.DOCX
        raise UnsupportedFileTypeError

    if not _parece_texto(amostra):
        raise UnsupportedFileTypeError

    # Markdown e texto com convencoes; a distincao vem da extensao, que aqui e apenas
    # uma dica de intencao e nao uma afirmacao sobre o conteudo.
    if filename.lower().endswith((".md", ".markdown")):
        return DocumentFormat.MARKDOWN
    return DocumentFormat.TEXT


def _e_docx(conteudo: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(conteudo)) as arquivo:
            nomes = set(arquivo.namelist())
    except (zipfile.BadZipFile, OSError):
        return False
    return "word/document.xml" in nomes


def _parece_texto(amostra: bytes) -> bool:
    """Aceita como texto o que decodifica em UTF-8 e nao tem bytes de controle.

    O byte nulo e o marcador mais confiavel de binario: nenhum texto real o contem, e
    todo formato binario tem varios.
    """
    if b"\x00" in amostra:
        return False
    try:
        texto = amostra.decode("utf-8")
    except UnicodeDecodeError:
        # Um corte no meio de um caractere multibyte nao torna o arquivo invalido.
        try:
            texto = amostra[: len(amostra) - 3].decode("utf-8")
        except UnicodeDecodeError:
            return False

    # Tab, quebra de linha e retorno sao esperados; outros controles indicam binario.
    permitidos = {"\t", "\n", "\r", "\f", "\v"}
    controles = sum(1 for c in texto if ord(c) < 32 and c not in permitidos)
    return controles == 0
