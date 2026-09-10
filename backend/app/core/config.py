"""Configuracao da aplicacao.

Toda configuracao vem de variaveis de ambiente, validada por Pydantic na inicializacao.
Se algo obrigatorio faltar, o processo falha ao subir — nunca em producao, no meio de um request.

Cada fase adiciona apenas as variaveis que efetivamente usa. Config declarada e nao usada e
codigo morto que ninguem tem coragem de remover depois.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, PostgresDsn, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Opcoes de conexao do libpq que o asyncpg nao reconhece. O Neon inclui as duas
# primeiras na connection string que exibe no painel.
_OPCOES_LIBPQ = frozenset(
    {"sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey", "target_session_attrs"}
)


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
    def _normalize_database_url(cls, value: object) -> object:
        """Adapta a connection string entregue pelas plataformas ao driver asyncpg.

        Duas correcoes, ambas para erros que custam tempo por nao dizerem o que esta
        errado:

        1. `postgresql://` -> `postgresql+asyncpg://`. Neon e Railway entregam a URL no
           formato sincrono; sem o driver explicito o SQLAlchemy tenta carregar psycopg2.

        2. Remove `sslmode`, `channel_binding` e afins. Sao opcoes do **libpq**, nao do
           asyncpg, que as rejeita com `invalid dsn: invalid connection option
           "sslmode"`. O Neon inclui as duas por padrao na string que exibe no painel.
           TLS continua ativo — e configurado em `create_engine`, ver app/db/session.py.
        """
        if not isinstance(value, str):
            return value

        if value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)

        parsed = urlsplit(value)
        if not parsed.query:
            return value

        preservados = [
            (chave, valor)
            for chave, valor in parse_qsl(parsed.query, keep_blank_values=True)
            if chave.lower() not in _OPCOES_LIBPQ
        ]
        return urlunsplit(parsed._replace(query=urlencode(preservados)))

    # --- Autenticacao ------------------------------------------------------
    # Sem default seguro de proposito: em producao, um segredo padrao permitiria a
    # qualquer um forjar tokens. O validador abaixo bloqueia o valor de dev fora de local.
    jwt_secret_key: SecretStr = SecretStr("dev-secret-local-apenas-trocar-em-producao")
    jwt_algorithm: str = "HS256"

    # Access curto porque nao ha como revoga-lo antes de expirar — a janela de dano de
    # um token vazado e exatamente esta.
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    @field_validator("jwt_secret_key")
    @classmethod
    def _reject_dev_secret_in_production(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        env = info.data.get("app_env")
        if env is Environment.PRODUCTION:
            secret = value.get_secret_value()
            # 32 bytes e o minimo da RFC 7518 para HS256.
            if secret.startswith("dev-secret") or len(secret.encode()) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY inseguro em producao. Gere com: "
                    'python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
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
