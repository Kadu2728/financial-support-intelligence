"""Interface de armazenamento de arquivos.

Quatro metodos, um problema concreto: o filesystem do Railway e efemero e todo redeploy
apaga o disco. Sem esta abstracao, os PDFs some no proximo deploy enquanto os registros
continuam no banco — a busca segue funcionando e so "abrir documento" quebra, o que faz
o sistema parecer saudavel estando quebrado no requisito central.

Justificativa completa em docs/adr/0007-abstracao-de-storage.md.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from typing import Protocol, runtime_checkable


class StorageError(Exception):
    """Falha ao acessar o armazenamento. Distinta de "objeto nao existe"."""


class ObjectNotFound(StorageError):
    pass


@runtime_checkable
class StorageBackend(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...


def build_storage_key(
    *, document_id: uuid.UUID, version_id: uuid.UUID, filename: str
) -> str:
    """Monta a chave do objeto a partir de ids, nunca do nome enviado pelo usuario.

    Derivar a chave do `filename` permitiria `../../etc/passwd` ou uma colisao entre
    dois uploads com o mesmo nome. Aqui so a EXTENSAO vem do arquivo original, e ainda
    assim filtrada — o nome de exibicao vive em `original_filename`, no banco.
    """
    sufixo = PurePosixPath(filename).suffix.lower()
    # Uma extensao so e aceita se for curta e alfanumerica; qualquer outra coisa vira
    # vazio em vez de entrar na chave.
    if not (1 < len(sufixo) <= 10 and sufixo[1:].isalnum()):
        sufixo = ""
    return f"documents/{document_id}/{version_id}{sufixo}"
