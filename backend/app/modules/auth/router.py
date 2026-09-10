from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.modules.auth.dependencies import AuthServiceDep, CurrentUser
from app.modules.auth.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenPair,
    UserProfile,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_context(request: Request) -> tuple[str | None, str | None]:
    """Contexto da sessao, para a tela de dispositivos conectados.

    O user-agent e truncado por ser entrada externa que vai para o banco.
    """
    user_agent = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return (user_agent[:512] if user_agent else None), ip


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Autentica e emite o par de tokens",
    responses={
        401: {"description": "Credenciais invalidas"},
        403: {"description": "Conta desativada"},
    },
)
async def login(payload: LoginRequest, request: Request, service: AuthServiceDep) -> LoginResponse:
    user_agent, ip = _client_context(request)
    tokens, user = await service.login(
        email=payload.email,
        password=payload.password,
        user_agent=user_agent,
        ip_address=ip,
    )
    return LoginResponse(tokens=tokens, user=UserProfile.model_validate(user))


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotaciona o refresh token",
    responses={401: {"description": "Sessao invalida, expirada ou reutilizada"}},
)
async def refresh(payload: RefreshRequest, request: Request, service: AuthServiceDep) -> TokenPair:
    user_agent, ip = _client_context(request)
    tokens, _ = await service.refresh(
        refresh_token=payload.refresh_token,
        user_agent=user_agent,
        ip_address=ip,
    )
    return tokens


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoga a sessao atual",
)
async def logout(payload: RefreshRequest, service: AuthServiceDep) -> Response:
    # Idempotente de proposito: o cliente ja descartou o cookie, e devolver erro por um
    # token desconhecido so produziria alerta inutil.
    await service.logout(refresh_token=payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=UserProfile,
    summary="Perfil do usuario autenticado",
    responses={401: {"description": "Nao autenticado"}},
)
async def me(user: CurrentUser) -> UserProfile:
    return UserProfile.model_validate(user)
