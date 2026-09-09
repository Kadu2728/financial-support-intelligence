from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.modules.auth.models import RefreshToken


class Role(StrEnum):
    """Papeis do sistema.

    ENUM em vez de tabela de dominio — justificativa em docs/adr/0006-role-como-enum.md.
    """

    ADMIN = "ADMIN"
    ANALYST = "ANALYST"


# `values_callable` faz o PostgreSQL armazenar os VALORES do enum, nao os nomes dos
# membros Python. Aqui nome e valor coincidem, mas depender dessa coincidencia e fragil:
# renomear um membro mudaria silenciosamente o dado gravado.
role_enum = Enum(
    Role,
    name="user_role",
    values_callable=lambda enum: [member.value for member in enum],
)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()

    # CITEXT: comparacao case-insensitive no banco. Evita ter que lembrar de aplicar
    # LOWER() em toda consulta por e-mail — esquecer uma vez cria uma conta duplicada.
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[Role] = mapped_column(role_enum, nullable=False, default=Role.ANALYST)

    # Desativar preserva o historico de consultas do usuario; deletar o destruiria.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<User {self.email} role={self.role.value}>"
