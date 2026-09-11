"""Configuracao da aplicacao.

Toda configuracao vem de variaveis de ambiente, validada por Pydantic na inicializacao.
Se algo obrigatorio faltar, o processo falha ao subir — nunca em producao, no meio de um request.

Cada fase adiciona apenas as variaveis que efetivamente usa. Config declarada e nao usada e
codigo morto que ninguem tem coragem de remover depois.
"""

from __future__ import annotations

import json
from contextlib import suppress
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, PostgresDsn, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Opcoes de conexao do libpq que o asyncpg nao reconhece. O Neon inclui as duas
# primeiras na connection string que exibe no painel.
_OPCOES_LIBPQ = frozenset(
    {"sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey", "target_session_attrs"}
)


class StorageKind(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


# Raiz do pacote backend, a partir deste arquivo (app/core/config.py -> backend/).
#
# O caminho do .env precisa ser absoluto. Com o valor relativo `.env`, o arquivo so e
# encontrado quando o processo sobe de dentro de `backend/` — rodar
# `uvicorn --app-dir backend` da raiz do repositorio carregava a configuracao INTEIRA
# vazia, sem erro nenhum, e a aplicacao caia no default de localhost.
# Configuracao que muda conforme o diretorio de onde se executa e armadilha silenciosa.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BACKEND_ROOT / ".env",
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

    # --- Storage de arquivos -----------------------------------------------
    # `local` grava em disco e serve apenas para desenvolvimento: o filesystem do
    # Railway e efemero e todo redeploy apagaria o acervo (ADR-0007).
    storage_backend: StorageKind = StorageKind.LOCAL
    storage_local_path: Path = _BACKEND_ROOT / "storage"

    s3_endpoint_url: str | None = None
    s3_bucket: str = "fsi-documents"
    s3_region: str = "auto"
    s3_access_key_id: SecretStr = SecretStr("")
    s3_secret_access_key: SecretStr = SecretStr("")

    @field_validator("s3_secret_access_key")
    @classmethod
    def _require_s3_credentials(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        """Falha ao subir, e nao no primeiro upload.

        Sem esta checagem, a aplicacao iniciaria normalmente e so quebraria quando um
        administrador tentasse enviar um documento — em producao, na frente do usuario.
        """
        if info.data.get("storage_backend") is StorageKind.S3 and not value.get_secret_value():
            raise ValueError("STORAGE_BACKEND=s3 exige S3_ACCESS_KEY_ID e S3_SECRET_ACCESS_KEY.")
        return value

    # --- Gemini ------------------------------------------------------------
    # Vazia por padrao: a aplicacao sobe sem a chave (admin de documentos e login
    # funcionam), mas o worker de ingestao e o copilot recusam-se a operar e dizem
    # por que. Em producao a chave e obrigatoria — validador abaixo.
    gemini_api_key: SecretStr = SecretStr("")
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_generation_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_seconds: float = 30.0
    # Lotes de 64 textos por chamada de embedding (docs/rag-design.md §1).
    gemini_embedding_batch_size: int = 64

    @field_validator("gemini_api_key")
    @classmethod
    def _require_gemini_in_production(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        if info.data.get("app_env") is Environment.PRODUCTION and not value.get_secret_value():
            raise ValueError("GEMINI_API_KEY e obrigatoria em producao.")
        return value

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.get_secret_value())

    # --- Worker de ingestao ------------------------------------------------
    # Roda dentro do processo da API (ADR-0004): um monolito com um so deploy. O
    # intervalo de polling e curto porque a fila e uma tabela e o SELECT e barato.
    worker_enabled: bool = True
    worker_poll_interval_seconds: float = 3.0
    # Job RUNNING ha mais tempo que isto e considerado orfao de um processo que
    # morreu e volta para a fila.
    worker_stale_after_minutes: int = 30

    # --- Busca e RAG (docs/rag-design.md §4-§6) ----------------------------
    search_candidates_per_leg: int = 30
    search_top_k: int = 8
    search_rrf_k: int = 60

    # Gate de evidencia. Em configuracao, nao em codigo: recalibrar nao pode exigir
    # deploy (ADR-0008).
    rag_min_top_score: float = 0.55
    rag_min_support_score: float = 0.45
    rag_min_support_count: int = 2
    rag_context_token_budget: int = 6000
    rag_generation_temperature: float = 0.2
    rag_max_question_chars: int = 1000

    # --- Rate limiting (Fase 10) -------------------------------------------
    # Por usuario, em memoria. Suficiente para uma instancia; multi-instancia
    # exigiria Redis — decisao adiada de proposito ate haver mais de uma instancia.
    rate_limit_copilot_per_minute: int = 20

    # --- Observabilidade ---------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = Field(
        default=False,
        description="Console legivel em dev, JSON estruturado em producao.",
    )

    # --- CORS --------------------------------------------------------------
    # Com o BFF (ADR-0003) o browser nunca chama o backend diretamente, entao esta lista
    # cobre apenas chamadas servidor-a-servidor e o acesso direto ao /docs em dev.
    # `NoDecode` e obrigatorio aqui. Para campos de tipo lista, o pydantic-settings
    # tenta `json.loads` no valor lido do .env ANTES de qualquer validador rodar —
    # entao `CORS_ORIGINS=http://localhost:3000` explodia com JSONDecodeError e o
    # validador abaixo nunca era alcancado. Sem um .env em disco o problema nao
    # aparece, o que o torna invisivel em teste que constroi Settings na mao.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Aceita `A,B` alem de JSON — plataformas de deploy nao lidam bem com listas."""
        if isinstance(value, str):
            texto = value.strip()
            # Uma lista JSON continua sendo aceita, para quem ja configurou assim.
            if texto.startswith("["):
                with suppress(json.JSONDecodeError):
                    return json.loads(texto)
            return [origin.strip() for origin in texto.split(",") if origin.strip()]
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
