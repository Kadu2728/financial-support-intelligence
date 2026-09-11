from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.feedback.models import Feedback, FeedbackRating, FeedbackReason


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        query_id: uuid.UUID,
        user_id: uuid.UUID,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
    ) -> Feedback:
        """Um feedback por usuario por consulta: reavaliar substitui, nao acumula."""
        existente = await self._session.scalar(
            select(Feedback).where(Feedback.query_id == query_id, Feedback.user_id == user_id)
        )
        if existente is not None:
            existente.rating = rating
            existente.reason = reason
            existente.comment = comment
            await self._session.flush()
            return existente

        feedback = Feedback(
            query_id=query_id, user_id=user_id, rating=rating, reason=reason, comment=comment
        )
        self._session.add(feedback)
        await self._session.flush()
        return feedback
