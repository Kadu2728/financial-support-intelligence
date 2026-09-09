"""Configuracao.

Erros de config aparecem em producao, no deploy, com o sistema fora do ar. Testar aqui e
barato e evita exatamente essa classe de descoberta tardia.
"""

from __future__ import annotations

from app.core.config import Environment, Settings


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
    settings = Settings(app_env=Environment.PRODUCTION)

    assert settings.is_production is True
    assert settings.docs_url is None


def test_docs_ficam_abertos_fora_de_producao() -> None:
    settings = Settings(app_env=Environment.LOCAL)

    assert settings.is_production is False
    assert settings.docs_url == "/docs"
