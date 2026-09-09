from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, uuid_pk

if TYPE_CHECKING:
    from app.modules.users.models import User


class RefreshToken(Base, CreatedAtMixin):
    """Refresh token persistido para permitir revogacao real.

    Um JWT puramente stateless nao pode ser invalidado antes de expirar — o "logout"
    apenas descarta o token no cliente, enquanto ele continua valido no servidor.
    Guardar o hash aqui torna o logout, a revogacao administrativa e a deteccao de
    reuso possiveis.

    Persistimos o HASH, nunca o token em claro: se o banco vazar, os tokens nao sao
    utilizaveis — mesma logica de uma tabela de senhas.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # Consulta quente do refresh: tokens ativos de um usuario. O indice parcial
        # ignora os ja revogados, que so crescem e nunca sao consultados por essa via.
        Index(
            "ix_refresh_tokens_user_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Contexto de auditoria de sessao: permite ao usuario ver e revogar dispositivos.
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens", lazy="raise")

    def __repr__(self) -> str:
        return f"<RefreshToken user={self.user_id} revoked={self.revoked_at is not None}>"
