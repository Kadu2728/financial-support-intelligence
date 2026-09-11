"""Configuracao.

Erros de config aparecem em producao, no deploy, com o sistema fora do ar. Testar aqui e
barato e evita exatamente essa classe de descoberta tardia.
"""

from __future__ import annotations

from app.core.config import Environment, Settings
from app.db.session import _connect_args


def test_cors_origins_aceita_string_separada_por_virgula() -> None:
    """Plataformas de deploy so entregam string; JSON em env var e fonte comum de erro."""
    settings = Settings(cors_origins="http://a.com, http://b.com")  # type: ignore[arg-type]

    assert settings.cors_origins == ["http://a.com", "http://b.com"]


def test_cors_origins_ignora_entradas_vazias() -> None:
    settings = Settings(cors_origins="http://a.com,,  ,http://b.com")  # type: ignore[arg-type]

    assert settings.cors_origins == ["http://a.com", "http://b.com"]


def test_cors_origins_aceita_lista() -> None:
    settings = Settings(cors_origins=["http://a.com"])

    assert settings.cors_origins == ["http://a.com"]


def test_docs_ficam_fechados_em_producao() -> None:
    """OpenAPI publico expoe a superficie inteira da API sem necessidade."""
    # Producao exige segredo forte (Fase 3) e chave do Gemini (Fase 5).
    settings = Settings(
        app_env=Environment.PRODUCTION, jwt_secret_key="k" * 48, gemini_api_key="chave"
    )

    assert settings.is_production is True
    assert settings.docs_url is None


def test_docs_ficam_abertos_fora_de_producao() -> None:
    settings = Settings(app_env=Environment.LOCAL)

    assert settings.is_production is False
    assert settings.docs_url == "/docs"


# --- Connection string das plataformas ------------------------------------
#
# O Neon exibe a string no formato do libpq. Cada ajuste abaixo evita um erro que
# nao diz o que esta errado — sao os que custam meia hora de depuracao no primeiro
# deploy.


def test_url_sincrona_ganha_o_driver_async() -> None:
    settings = Settings(database_url="postgresql://u:p@host.neon.tech/db")

    assert str(settings.database_url).startswith("postgresql+asyncpg://")


def test_sslmode_e_removido_da_url() -> None:
    """asyncpg rejeita `sslmode` com `invalid dsn: invalid connection option`.

    E opcao do libpq, nao do driver. TLS e reativado em `_connect_args`.
    """
    settings = Settings(database_url="postgresql://u:p@host.neon.tech/db?sslmode=require")

    assert "sslmode" not in str(settings.database_url)


def test_channel_binding_e_removido_da_url() -> None:
    """O Neon inclui este parametro junto do sslmode."""
    settings = Settings(
        database_url="postgresql://u:p@host.neon.tech/db?sslmode=require&channel_binding=require"
    )

    url = str(settings.database_url)
    assert "channel_binding" not in url
    assert "sslmode" not in url


def test_parametros_desconhecidos_sao_preservados() -> None:
    """Remover apenas o que o asyncpg nao entende; o resto pode ser intencional."""
    settings = Settings(
        database_url="postgresql://u:p@host.neon.tech/db?sslmode=require&application_name=fsi"
    )

    assert "application_name=fsi" in str(settings.database_url)


def test_tls_e_exigido_em_host_remoto() -> None:
    """Removido o sslmode, sem isto a conexao com o Neon sairia sem TLS."""
    settings = Settings(
        database_url="postgresql://u:p@ep-x-pooler.aws.neon.tech/db?sslmode=require"
    )

    assert _connect_args(settings)["ssl"] == "require"


def test_tls_nao_e_exigido_em_localhost() -> None:
    """Um Postgres de desenvolvimento normalmente nao tem certificado."""
    settings = Settings(database_url="postgresql://postgres:postgres@localhost:5432/fsi")

    assert "ssl" not in _connect_args(settings)


def test_cache_de_prepared_statements_desligado_sempre() -> None:
    """Obrigatorio atras do pooler do Neon em modo transaction."""
    settings = Settings(database_url="postgresql://u:p@ep-x-pooler.aws.neon.tech/db")

    assert _connect_args(settings)["statement_cache_size"] == 0
