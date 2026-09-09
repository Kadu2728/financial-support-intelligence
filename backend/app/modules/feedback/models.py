from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, uuid_pk

if TYPE_CHECKING:
    from app.modules.queries.models import Query
    from app.modules.users.models import User


class FeedbackRating(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class FeedbackReason(StrEnum):
    """Motivos de feedback negativo.

    Um enum fechado, e nao texto livre, porque estes valores viram metrica agregada no
    Intelligence. "Resposta incorreta" e "fonte errada" pedem acoes diferentes:
    a primeira aponta para o prompt ou o modelo, a segunda para o retrieval.
    """

    INCORRECT = "INCORRECT"
    INCOMPLETE = "INCOMPLETE"
    WRONG_SOURCE = "WRONG_SOURCE"
    OUTDATED = "OUTDATED"
    OTHER = "OTHER"


feedback_rating_enum = Enum(
    FeedbackRating,
    name="feedback_rating",
    values_callable=lambda enum: [member.value for member in enum],
)

feedback_reason_enum = Enum(
    FeedbackReason,
    name="feedback_reason",
    values_callable=lambda enum: [member.value for member in enum],
)


class Feedback(Base, CreatedAtMixin):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    rating: Mapped[FeedbackRating] = mapped_column(feedback_rating_enum, nullable=False)
    reason: Mapped[FeedbackReason | None] = mapped_column(feedback_reason_enum, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    query: Mapped[Query] = relationship(back_populates="feedback", lazy="raise")
    user: Mapped[User] = relationship(lazy="raise")

    __table_args__ = (
        # Um feedback por usuario por consulta. Reavaliar substitui o anterior em vez de
        # acumular votos e distorcer a metrica.
        UniqueConstraint("query_id", "user_id"),
        # Agregacao do Intelligence: feedback negativo por periodo.
        Index("ix_feedback_rating_created", "rating", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Feedback query={self.query_id} {self.rating.value}>"
