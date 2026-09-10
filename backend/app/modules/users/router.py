"""Endpoints de usuarios.

Escopo mínimo na Fase 3: apenas o que exercita a autorizacao por papel de ponta a
ponta. O CRUD completo entra quando houver tela que o consuma.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.modules.auth.dependencies import AuthServiceDep, RequireAdmin
from app.modules.auth.schemas import UserProfile
from app.modules.users.schemas import CreateUserRequest

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "",
    response_model=UserProfile,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastra um usuario",
    responses={
        401: {"description": "Nao autenticado"},
        403: {"description": "Requer papel ADMIN"},
        409: {"description": "E-mail ja cadastrado"},
    },
)
async def create_user(
    payload: CreateUserRequest,
    admin: RequireAdmin,
    service: AuthServiceDep,
) -> UserProfile:
    """Cadastro e restrito a ADMIN.

    Nao ha auto-registro: e uma ferramenta interna, e o acesso e concedido, nao
    solicitado.
    """
    user = await service.create_user(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role,
    )
    return UserProfile.model_validate(user)
