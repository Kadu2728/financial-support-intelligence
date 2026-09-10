"""Autenticacao e autorizacao como dependencies do FastAPI.

Separacao deliberada em duas perguntas distintas:

- `require_role` responde "este papel pode acessar esta ROTA?"
- o service responde "este usuario pode acessar este REGISTRO?"

As duas sao necessarias. Um ANALYST pode acessar `GET /queries/{id}`; nao pode acessar
a consulta de OUTRO analista. Somente a primeira pergunta cabe numa dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import SessionDep, SettingsDep
from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import InvalidTokenError, decode_access_token
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.auth.service import AuthService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository

logger = structlog.get_logger(__name__)

# auto_error=False para que a ausencia de header produza o envelope de erro padrao da
# aplicacao, e nao o 403 cru do Starlette com formato proprio.
_bearer = HTTPBearer(auto_error=False)


def get_user_repository(session: SessionDep) -> UserRepository:
    """Repositorio como dependency, e nao construido dentro de quem o usa.

    Sem isto, `get_current_user` ficaria acoplado a sessao concreta e so seria
    testavel com banco real — o que empurraria o teste de autorizacao para a suite
    de integracao, onde ele roda menos vezes.
    """
    return UserRepository(session)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_auth_service(
    settings: SettingsDep, session: SessionDep, users: UserRepositoryDep
) -> AuthService:
    return AuthService(
        settings=settings,
        users=users,
        refresh_tokens=RefreshTokenRepository(session),
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    request: Request,
    settings: SettingsDep,
    users: UserRepositoryDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Resolve o usuario autenticado a partir do access token.

    Consulta o banco a cada requisicao — o token prova identidade, mas nao prova que a
    conta continua ativa. Sem esta leitura, desativar um usuario so teria efeito quando
    o token dele expirasse.
    """
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Autenticacao necessaria.")

    try:
        claims = decode_access_token(settings, credentials.credentials)
    except InvalidTokenError as exc:
        logger.info("token_rejected", reason=str(exc))
        raise UnauthorizedError("Sessao invalida ou expirada.") from exc

    user = await users.get_by_id(claims.user_id)
    if user is None:
        raise UnauthorizedError("Sessao invalida ou expirada.")

    if not user.is_active:
        raise UnauthorizedError("Esta conta esta desativada.")

    # Disponibiliza o usuario ao middleware de log sem re-decodificar o token.
    request.state.user_id = str(user.id)
    structlog.contextvars.bind_contextvars(user_id=str(user.id))

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(
    *allowed: Role,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    """Restringe a rota aos papeis informados.

    Usar como dependency e nao como decorator faz a exigencia aparecer na assinatura do
    endpoint e no OpenAPI — quem le a rota ve quem pode chama-la.
    """
    permitidos = frozenset(allowed)

    async def _check(user: CurrentUser) -> User:
        if user.role not in permitidos:
            logger.warning(
                "authorization_denied",
                user_id=str(user.id),
                role=user.role.value,
                required=[r.value for r in permitidos],
            )
            raise ForbiddenError
        return user

    return _check


RequireAdmin = Annotated[User, Depends(require_role(Role.ADMIN))]


def ensure_owner_or_admin(user: User, owner_id: object) -> None:
    """Autorizacao no nivel do registro.

    Levanta 404, nao 403: responder "proibido" confirmaria que o recurso existe, o que
    permitiria descobrir ids validos de outros usuarios por tentativa.
    """
    if user.role is Role.ADMIN:
        return
    if str(owner_id) != str(user.id):
        logger.info("ownership_denied", user_id=str(user.id), attempted_owner=str(owner_id))
        raise NotFoundError
