"""Dependencies compartilhadas do FastAPI.

O engine e a session factory vivem em `app.state`, criados no lifespan. Injetar por
dependency (em vez de um singleton de modulo) e o que permite ao teste montar a
aplicacao apontando para outro banco, sem variavel global e sem monkeypatch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import get_db
from app.integrations.gemini.client import GeminiClient, GeminiNotConfiguredError


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


async def get_session(
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    async for session in get_db(session_factory):
        yield session


def get_gemini(request: Request) -> GeminiClient:
    """Cliente do Gemini criado no lifespan.

    Levanta 503 com causa explicita quando a chave nao esta configurada — a
    alternativa, um 500 generico no primeiro uso, esconderia o motivo.
    """
    client: GeminiClient | None = getattr(request.app.state, "gemini", None)
    if client is None:
        raise GeminiNotConfiguredError
    return client


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
GeminiDep = Annotated[GeminiClient, Depends(get_gemini)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
