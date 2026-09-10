from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.users.models import Role


class LoginRequest(BaseModel):
    email: EmailStr
    # O limite superior existe para nao passar megabytes ao argon2, que os processaria
    # e transformaria o login numa forma barata de consumir CPU do servidor.
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - esquema HTTP, nao credencial
    # Segundos ate expirar. O cliente agenda a renovacao a partir disto, em vez de
    # decodificar o JWT — que exigiria conhecer o formato do token.
    expires_in: int


class UserProfile(BaseModel):
    """Usuario autenticado. Nunca inclui `password_hash`.

    Um schema de saida explicito e o que impede o hash de vazar por acidente quando um
    campo novo e adicionado ao modelo.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class LoginResponse(BaseModel):
    tokens: TokenPair
    user: UserProfile
