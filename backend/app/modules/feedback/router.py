"""Feedback sobre respostas.

Vive sob /queries/{id}/feedback porque e um atributo da consulta, nao um recurso
solto. O motivo e um enum fechado: vira metrica agregada no Intelligence, e
"resposta incorreta" e "fonte errada" pedem acoes diferentes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from app.core.dependencies import SessionDep
from app.core.errors import NotFoundError
from app.modules.auth.dependencies import CurrentUser, ensure_owner_or_admin
from app.modules.feedback.models import FeedbackRating, FeedbackReason
from app.modules.feedback.repository import FeedbackRepository
from app.modules.queries.repository import QueryRepository
from app.modules.queries.schemas import FeedbackOut

router = APIRouter(prefix="/queries", tags=["feedback"])


class FeedbackRequest(BaseModel):
    rating: FeedbackRating
    reason: FeedbackReason | None = None
    comment: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _motivo_so_no_negativo(self) -> FeedbackRequest:
        # Um motivo em feedback positivo poluiria a metrica de causas de erro.
        if self.rating is FeedbackRating.POSITIVE:
            self.reason = None
        return self


@router.put("/{query_id}/feedback", response_model=FeedbackOut, summary="Avalia uma resposta")
async def give_feedback(
    query_id: uuid.UUID, corpo: FeedbackRequest, session: SessionDep, user: CurrentUser
) -> FeedbackOut:
    query = await QueryRepository(session).get(query_id)
    if query is None:
        raise NotFoundError("Consulta nao encontrada.")
    ensure_owner_or_admin(user, query.user_id)

    feedback = await FeedbackRepository(session).upsert(
        query_id=query_id,
        user_id=user.id,
        rating=corpo.rating,
        reason=corpo.reason,
        comment=corpo.comment,
    )
    return FeedbackOut.model_validate(feedback)
