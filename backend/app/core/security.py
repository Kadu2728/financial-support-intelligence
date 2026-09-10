"""Primitivas de seguranca: hash de senha, JWT e tokens opacos.

Funcoes puras, sem banco e sem HTTP. Isso as torna testaveis em isolamento e mantem a
politica de seguranca em um unico arquivo auditavel.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

# argon2id com os parametros padrao da biblioteca, que seguem a recomendacao da RFC 9106.
# Preferido a bcrypt por resistir melhor a ataque com GPU e por nao ter o limite de
# 72 bytes que trunca senhas longas em silencio.
_hasher = PasswordHasher()


class TokenType(StrEnum):
    ACCESS = "access"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica a senha. Nunca levanta — retorna False para qualquer falha.

    Deixar a excecao escapar transformaria um hash corrompido em erro 500 em vez de
    "credenciais invalidas", vazando a existencia do usuario pela diferenca de resposta.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError, ValueError):
        # VerificationError e a classe-pai de VerifyMismatchError e cobre tambem
        # "decoding failed", que e o que um hash corrompido no banco produz.
        return False


def needs_rehash(password_hash: str) -> bool:
    """Indica se o hash usa parametros antigos.

    Quando o custo do argon2 e elevado, os hashes existentes continuam validos mas
    desatualizados. Rehashear no proximo login migra a base sem forcar troca de senha.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return False


# Custo fixo pago quando o e-mail nao existe, para que a resposta demore o mesmo tanto
# de um login com senha errada. Sem isso, o tempo de resposta revela quais e-mails
# estao cadastrados.
_DUMMY_HASH = _hasher.hash("timing-attack-mitigation")


def waste_password_verification_time() -> None:
    verify_password("nao-importa", _DUMMY_HASH)


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    role: str
    expires_at: datetime


def create_access_token(
    settings: Settings, *, user_id: uuid.UUID, role: str
) -> tuple[str, datetime]:
    """Emite um access token JWT.

    O `role` viaja no token para que a autorizacao nao precise consultar o banco a cada
    requisicao. O custo e a latencia da revogacao: rebaixar um ADMIN so tem efeito
    quando o token atual expira. Com 15 minutos de validade, a janela e aceitavel — e e
    o que justifica um access token curto.
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        # Distingue access de refresh. Sem isto, um refresh token roubado poderia ser
        # usado como access diretamente.
        "type": TokenType.ACCESS.value,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at


class InvalidTokenError(Exception):
    """Token ausente, malformado, expirado ou com assinatura invalida."""


def decode_access_token(settings: Settings, token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            # Lista explicita de algoritmos: aceitar o algoritmo declarado no proprio
            # token permitiria o ataque de trocar HS256 por "none".
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("type") != TokenType.ACCESS.value:
        raise InvalidTokenError("tipo de token incorreto")

    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("sub invalido") from exc

    role = payload.get("role")
    if not isinstance(role, str):
        raise InvalidTokenError("role ausente")

    return AccessTokenClaims(
        user_id=user_id,
        role=role,
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )


# --- Refresh tokens --------------------------------------------------------
#
# Strings opacas, nao JWT. Validar um refresh exige consultar o banco de qualquer
# forma — e o que permite revogar. Como a consulta e obrigatoria, o JWT nao agregaria
# nada e so adicionaria superficie (claims que envelhecem, algoritmo a validar).


def generate_refresh_token() -> str:
    """32 bytes de entropia criptografica, em base64 url-safe."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256 do token, que e o que vai para o banco.

    Nao usa argon2 de proposito: o token ja tem entropia alta o bastante para tornar
    forca bruta inviavel, e o refresh e verificado a cada renovacao — um hash lento
    seria custo por requisicao sem ganho. O objetivo aqui e apenas que um vazamento do
    banco nao entregue tokens utilizaveis.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_token_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
