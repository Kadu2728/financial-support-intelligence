"""Primitivas de seguranca.

Funcoes puras, testadas sem banco e sem HTTP. Cada teste aqui cobre uma propriedade de
seguranca que, se quebrar, nao produz erro visivel — apenas deixa o sistema vulneravel.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Environment, Settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env=Environment.TEST, jwt_secret_key="segredo-de-teste-com-tamanho-suficiente"
    )


# --- Senhas ----------------------------------------------------------------


def test_senha_correta_e_aceita() -> None:
    assert verify_password("senha-muito-secreta", hash_password("senha-muito-secreta"))


def test_senha_incorreta_e_rejeitada() -> None:
    assert not verify_password("errada", hash_password("senha-muito-secreta"))


def test_hash_nao_contem_a_senha() -> None:
    assert "senha-muito-secreta" not in hash_password("senha-muito-secreta")


def test_hashes_da_mesma_senha_sao_diferentes() -> None:
    """Salt por hash: sem ele, senhas iguais teriam hashes iguais e um vazamento
    revelaria quais usuarios compartilham senha."""
    assert hash_password("mesma-senha") != hash_password("mesma-senha")


def test_hash_usa_argon2id() -> None:
    assert hash_password("x").startswith("$argon2id$")


@pytest.mark.parametrize("hash_invalido", ["", "nao-e-um-hash", "$argon2id$corrompido"])
def test_hash_malformado_retorna_false_em_vez_de_explodir(hash_invalido: str) -> None:
    """Deixar a excecao escapar transformaria um hash corrompido em erro 500, e a
    diferenca de resposta revelaria a existencia do usuario."""
    assert verify_password("qualquer", hash_invalido) is False


# --- Access token ----------------------------------------------------------


def test_token_carrega_usuario_e_papel(settings: Settings) -> None:
    user_id = uuid.uuid4()
    token, _ = create_access_token(settings, user_id=user_id, role="ADMIN")

    claims = decode_access_token(settings, token)

    assert claims.user_id == user_id
    assert claims.role == "ADMIN"


def test_token_assinado_com_outro_segredo_e_rejeitado(settings: Settings) -> None:
    outro = Settings(
        app_env=Environment.TEST, jwt_secret_key="um-segredo-completamente-diferente-e-longo"
    )
    token, _ = create_access_token(outro, user_id=uuid.uuid4(), role="ANALYST")

    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, token)


def test_token_expirado_e_rejeitado(settings: Settings) -> None:
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "ANALYST",
        "type": "access",
        "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
        "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, token)


def test_token_com_algoritmo_none_e_rejeitado(settings: Settings) -> None:
    """O ataque classico contra JWT: trocar o algoritmo por "none" e remover a
    assinatura. A lista explicita de algoritmos no decode e o que bloqueia."""
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "ADMIN",
        "type": "access",
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, key="", algorithm="none")

    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, token)


def test_token_sem_claim_type_e_rejeitado(settings: Settings) -> None:
    """Sem a checagem de `type`, um refresh token poderia ser usado como access."""
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "ADMIN",
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, token)


@pytest.mark.parametrize("lixo", ["", "nao.e.jwt", "a.b.c", "Bearer xyz"])
def test_token_malformado_e_rejeitado(settings: Settings, lixo: str) -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, lixo)


def test_tokens_do_mesmo_usuario_sao_distintos(settings: Settings) -> None:
    """O `jti` garante unicidade mesmo dentro do mesmo segundo — necessario para
    uma futura blocklist por token."""
    user_id = uuid.uuid4()
    primeiro, _ = create_access_token(settings, user_id=user_id, role="ANALYST")
    segundo, _ = create_access_token(settings, user_id=user_id, role="ANALYST")

    assert primeiro != segundo


# --- Refresh token ---------------------------------------------------------


def test_refresh_tokens_sao_unicos() -> None:
    assert len({generate_refresh_token() for _ in range(500)}) == 500


def test_refresh_token_tem_entropia_suficiente() -> None:
    """32 bytes em base64 url-safe. Menos que isso torna forca bruta viavel."""
    assert len(generate_refresh_token()) >= 43


def test_hash_do_refresh_e_deterministico() -> None:
    token = generate_refresh_token()
    assert hash_refresh_token(token) == hash_refresh_token(token)


def test_hash_do_refresh_nao_revela_o_token() -> None:
    token = generate_refresh_token()
    digest = hash_refresh_token(token)

    assert token not in digest
    assert len(digest) == 64  # SHA-256 em hex


# --- Configuracao ----------------------------------------------------------


def test_segredo_de_desenvolvimento_e_recusado_em_producao() -> None:
    """Falha ao subir, nao em producao silenciosamente: com o segredo padrao,
    qualquer um forjaria um token de ADMIN."""
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            app_env=Environment.PRODUCTION,
            jwt_secret_key="dev-secret-local-apenas-trocar-em-producao",
        )


def test_segredo_curto_e_recusado_em_producao() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(app_env=Environment.PRODUCTION, jwt_secret_key="curto")


def test_segredo_forte_e_aceito_em_producao() -> None:
    settings = Settings(
        app_env=Environment.PRODUCTION,
        jwt_secret_key="k" * 48,
        gemini_api_key="chave",
    )
    assert settings.is_production


def test_segredo_nao_aparece_ao_imprimir_settings() -> None:
    """SecretStr existe para que o segredo nao vaze em log de erro ou repr."""
    settings = Settings(
        app_env=Environment.TEST, jwt_secret_key="segredo-que-nao-pode-vazar-de-jeito-nenhum"
    )

    assert "segredo-que-nao-pode-vazar-de-jeito-nenhum" not in repr(settings)
    assert "segredo-que-nao-pode-vazar-de-jeito-nenhum" not in str(settings)
