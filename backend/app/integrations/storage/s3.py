"""Armazenamento S3-compatible (Cloudflare R2 em producao).

R2 pela ausencia de custo de egress: cada visualizacao de documento e uma leitura, e
em S3 tradicional isso e a linha que cresce na fatura.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from app.integrations.storage.base import ObjectNotFound, StorageError

if TYPE_CHECKING:
    from app.core.config import Settings


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depende do extra instalado
            raise StorageError(
                "STORAGE_BACKEND=s3 exige boto3. Instale com: pip install -e '.[s3]'"
            ) from exc

        self._bucket = settings.s3_bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
            aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            region_name=settings.s3_region,
        )

    # boto3 e sincrono. `to_thread` evita travar o event loop em cada chamada.
    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        def _ler() -> bytes:
            try:
                resposta = self._client.get_object(Bucket=self._bucket, Key=key)
            except self._client.exceptions.NoSuchKey as exc:
                raise ObjectNotFound(key) from exc
            corpo: bytes = resposta["Body"].read()
            return corpo

        return await asyncio.to_thread(_ler)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        def _verificar() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except Exception:
                return False
            return True

        return await asyncio.to_thread(_verificar)
