"""Armazenamento em disco, para desenvolvimento.

Nao usar em producao: o filesystem do Railway e efemero (ADR-0007).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.integrations.storage.base import ObjectNotFound, StorageError


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _caminho(self, key: str) -> Path:
        destino = (self._root / key).resolve()
        # Defesa em profundidade. A chave ja e gerada pelo servidor a partir de UUIDs,
        # mas um bug futuro que a derive de entrada do usuario nao pode virar escrita
        # fora do diretorio de storage.
        if not destino.is_relative_to(self._root):
            raise StorageError(f"chave invalida: {key}")
        return destino

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        destino = self._caminho(key)

        def _escrever() -> None:
            destino.parent.mkdir(parents=True, exist_ok=True)
            # Escreve em arquivo temporario e move: um processo interrompido no meio
            # deixa o temporario, nunca um objeto truncado no lugar do definitivo.
            temporario = destino.with_suffix(destino.suffix + ".tmp")
            temporario.write_bytes(data)
            temporario.replace(destino)

        # to_thread porque I/O de disco e bloqueante e travaria o event loop.
        await asyncio.to_thread(_escrever)

    async def get(self, key: str) -> bytes:
        destino = self._caminho(key)
        try:
            return await asyncio.to_thread(destino.read_bytes)
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc

    async def delete(self, key: str) -> None:
        destino = self._caminho(key)
        await asyncio.to_thread(destino.unlink, True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._caminho(key).is_file)
