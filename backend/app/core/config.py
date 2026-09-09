"""Configuracao da aplicacao.

Toda configuracao vem de variaveis de ambiente, validada por Pydantic na inicializacao.
Se algo obrigatorio faltar, o processo falha ao subir — nunca em producao, no meio de um request.

Cada fase adiciona apenas as variaveis que efetivamente usa. Config declarada e nao usada e
codigo morto que ninguem tem coragem de remover depois.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Aplicacao ---------------------------------------------------------
    app_name: str = "Financial Support Intelligence"
    app_env: Environment = Environment.LOCAL
    api_v1_prefix: str = "/api/v1"

    # --- Banco de dados ----------------------------------------------------
    # Neon: usar a connection string POOLED (host com `-pooler`). Ver app/db/session.py.
    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/fsi"
    )
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 5

    @field_validator("database_url", mode="before")
    @classmethod
    def _require_async_driver(cls, value: object) -> object:
        """Converte `postgresql://` para `postgresql+asyncpg://`.

        Neon, Railway e a maioria das plataformas entregam a URL no formato sincrono.
        Sem o driver async explicito, o SQLAlchemy carrega psycopg2 e falha com um erro
        que nao diz o que esta errado.
        """
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    # --- Observabilidade ---------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = Field(
        default=False,
        description="Console legivel em dev, JSON estruturado em producao.",
    )

    # --- CORS --------------------------------------------------------------
    # Com o BFF (ADR-0003) o browser nunca chama o backend diretamente, entao esta lista
    # cobre apenas chamadas servidor-a-servidor e o acesso direto ao /docs em dev.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Aceita `A,B` alem de JSON — plataformas de deploy nao lidam bem com listas."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def docs_url(self) -> str | None:
        """OpenAPI publico nao vai para producao: expoe superficie sem necessidade."""
        return None if self.is_production else "/docs"


@lru_cache
def get_settings() -> Settings:
    """Instancia unica. O cache tambem permite override limpo nos testes."""
    return Settings()
