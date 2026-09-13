"""Escolha do backend de storage pela configuracao (ADR-0007).

Funcao pura de construcao, usada pela API (dependency), pelo worker (lifespan) e pelo
CLI. Um lugar so decide o backend; os tres nunca divergem.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, StorageKind
from app.integrations.storage.base import StorageBackend
from app.integrations.storage.local import LocalStorage


def build_storage(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> StorageBackend:
    if settings.storage_backend is StorageKind.S3:
        from app.integrations.storage.s3 import S3Storage

        return S3Storage(settings)
    if settings.storage_backend is StorageKind.DB:
        from app.integrations.storage.db import DbStorage

        return DbStorage(session_factory)
    return LocalStorage(settings.storage_local_path)
