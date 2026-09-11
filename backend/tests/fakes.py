"""Repositories em memoria.

Permitem testar a regra de negocio do `AuthService` — rotacao, deteccao de reuso,
resposta a conta desativada — sem banco. O que estes fakes NAO cobrem (constraints,
CITEXT, transacoes) fica para os testes marcados `integration`, que rodam contra
PostgreSQL real.

A fronteira e honesta: aqui se testa a decisao, la se testa a persistencia.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.auth.models import RefreshToken
from app.modules.users.models import Role, User


class FakeUserRepository:
    def __init__(self, users: list[User] | None = None) -> None:
        self._users: dict[uuid.UUID, User] = {u.id: u for u in (users or [])}
        self.password_updates: list[tuple[uuid.UUID, str]] = []
        self.logins_registrados: list[uuid.UUID] = []

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        # CITEXT no banco; aqui a normalizacao e explicita.
        alvo = email.casefold()
        return next((u for u in self._users.values() if u.email.casefold() == alvo), None)

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        full_name: str,
        role: Role = Role.ANALYST,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            role=role,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self._users[user.id] = user
        return user

    async def touch_last_login(self, user_id: uuid.UUID) -> None:
        self.logins_registrados.append(user_id)

    async def update_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None:
        self.password_updates.append((user_id, password_hash))
        if user := self._users.get(user_id):
            user.password_hash = password_hash


class FakeRefreshTokenRepository:
    def __init__(self) -> None:
        self._tokens: dict[uuid.UUID, RefreshToken] = {}

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> RefreshToken:
        token = RefreshToken(
            id=uuid.uuid4(),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked_at=None,
            user_agent=user_agent,
            ip_address=ip_address,
            created_at=datetime.now(UTC),
        )
        self._tokens[token.id] = token
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return next((t for t in self._tokens.values() if t.token_hash == token_hash), None)

    async def revoke(self, token_id: uuid.UUID) -> None:
        token = self._tokens.get(token_id)
        if token is not None and token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        ativos = [t for t in self._tokens.values() if t.user_id == user_id and t.revoked_at is None]
        agora = datetime.now(UTC)
        for token in ativos:
            token.revoked_at = agora
        return len(ativos)

    # --- Auxiliares de teste ---

    @property
    def ativos(self) -> list[RefreshToken]:
        return [t for t in self._tokens.values() if t.revoked_at is None]

    @property
    def total(self) -> int:
        return len(self._tokens)


class FakeSession:
    """Sessao falsa que registra os commits.

    Existe para o commit da deteccao de reuso (ver AuthService.refresh). Contar os
    commits permite testar que ele acontece — mas nao substitui o teste de integracao,
    que e o unico capaz de provar que a revogacao sobrevive ao rollback real.
    """

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass
