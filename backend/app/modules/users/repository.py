from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import Role, User


class UserRepository:
    """Acesso a `users`. Nao conhece HTTP nem regra de negocio."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Busca por e-mail.

        Sem `LOWER()`: a coluna e CITEXT e a comparacao ja e case-insensitive no banco.
        """
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        full_name: str,
        role: Role = Role.ANALYST,
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            role=role,
        )
        self._session.add(user)
        # Flush, nao commit: a transacao pertence a borda da requisicao (app/db/session.py).
        # Assim o cadastro de um usuario e o que mais vier junto continuam atomicos.
        await self._session.flush()
        return user

    async def touch_last_login(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(User).where(User.id == user_id).values(last_login_at=datetime.now(UTC))
        )

    async def update_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None:
        await self._session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )
