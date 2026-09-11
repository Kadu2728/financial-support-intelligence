"""Regra de negocio da autenticacao.

Nao conhece HTTP: recebe e devolve objetos de dominio, e sinaliza falha levantando as
excecoes de `app.core.errors`. Isso permite testar login, rotacao e deteccao de reuso
sem subir a aplicacao.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode, UnauthorizedError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    refresh_token_expiry,
    verify_password,
    waste_password_verification_time,
)
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.auth.schemas import TokenPair
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository

logger = structlog.get_logger(__name__)


class InvalidCredentialsError(AppError):
    """Mensagem deliberadamente vaga.

    Distinguir "e-mail nao existe" de "senha errada" entregaria a um atacante uma forma
    de enumerar contas validas.
    """

    status_code = 401
    code = ErrorCode.INVALID_CREDENTIALS
    message = "E-mail ou senha incorretos."


class InactiveUserError(AppError):
    status_code = 403
    code = ErrorCode.INACTIVE_USER
    message = "Esta conta esta desativada."


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        session: AsyncSession,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
    ) -> None:
        self._settings = settings
        # Necessaria apenas para o commit da deteccao de reuso; ver `refresh`.
        self._session = session
        self._users = users
        self._refresh_tokens = refresh_tokens

    # --- Login -------------------------------------------------------------

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[TokenPair, User]:
        user = await self._users.get_by_email(email)

        if user is None:
            # Paga o mesmo custo de um argon2 real. Sem isto, a resposta para um e-mail
            # inexistente volta em microssegundos e a diferenca de tempo revela quais
            # contas existem.
            waste_password_verification_time()
            logger.info("login_failed", reason="unknown_email")
            raise InvalidCredentialsError

        if not verify_password(password, user.password_hash):
            logger.info("login_failed", reason="bad_password", user_id=str(user.id))
            raise InvalidCredentialsError

        # Verificado DEPOIS da senha, de proposito: responder "conta desativada" antes
        # de validar a senha confirmaria a existencia do e-mail para quem so chutou.
        if not user.is_active:
            logger.info("login_failed", reason="inactive", user_id=str(user.id))
            raise InactiveUserError

        # O custo do argon2 sobe com o tempo; migrar no login evita forcar troca de senha.
        if needs_rehash(user.password_hash):
            await self._users.update_password_hash(user.id, hash_password(password))

        await self._users.touch_last_login(user.id)
        tokens = await self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)

        logger.info("login_succeeded", user_id=str(user.id), role=user.role.value)
        return tokens, user

    # --- Refresh -----------------------------------------------------------

    async def refresh(
        self,
        *,
        refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[TokenPair, User]:
        """Rotaciona o refresh token, detectando reuso.

        Rotacao sem deteccao de reuso e teatro: o atacante que copiou o token continua
        renovando indefinidamente ao lado do usuario legitimo. Aqui, um token ja
        revogado que reaparece derruba todas as sessoes do usuario.
        """
        stored = await self._refresh_tokens.get_by_hash(hash_refresh_token(refresh_token))

        if stored is None:
            raise UnauthorizedError("Sessao invalida. Faca login novamente.")

        if stored.revoked_at is not None:
            # Este token ja foi usado e substituido. Se reapareceu, ou vazou ou foi
            # copiado — e nao ha como saber qual sessao e a legitima.
            revogadas = await self._refresh_tokens.revoke_all_for_user(stored.user_id)

            # COMMIT EXPLICITO, obrigatorio. A excecao levantada logo abaixo dispara o
            # rollback na borda da requisicao (app/db/session.py), que desfaria a
            # revogacao recem-feita. Sem este commit a deteccao de reuso nao tem efeito
            # nenhum: o token roubado continua valido e o atacante segue renovando.
            #
            # E o unico ponto do sistema que commita fora da borda, porque e o unico em
            # que uma escrita precisa persistir apesar de a requisicao terminar em erro.
            await self._session.commit()

            logger.warning(
                "refresh_token_reuse_detected",
                user_id=str(stored.user_id),
                sessions_revoked=revogadas,
            )
            raise UnauthorizedError("Sessao invalida. Faca login novamente.")

        if stored.expires_at <= datetime.now(UTC):
            raise UnauthorizedError("Sessao expirada. Faca login novamente.")

        user = await self._users.get_by_id(stored.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("Sessao invalida. Faca login novamente.")

        # Revoga o token usado ANTES de emitir o novo: se a emissao falhar, o antigo
        # ja nao vale, e o pior caso e um login a mais — nunca dois tokens validos.
        await self._refresh_tokens.revoke(stored.id)
        tokens = await self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)

        logger.info("refresh_succeeded", user_id=str(user.id))
        return tokens, user

    # --- Logout ------------------------------------------------------------

    async def logout(self, *, refresh_token: str) -> None:
        """Revoga a sessao. Idempotente: um token desconhecido nao e erro.

        O cliente ja descartou o cookie quando chega aqui; devolver erro so produziria
        um alerta inutil para o usuario.
        """
        stored = await self._refresh_tokens.get_by_hash(hash_refresh_token(refresh_token))
        if stored is not None and stored.revoked_at is None:
            await self._refresh_tokens.revoke(stored.id)
            logger.info("logout", user_id=str(stored.user_id))

    async def logout_all(self, *, user_id: uuid.UUID) -> int:
        return await self._refresh_tokens.revoke_all_for_user(user_id)

    # --- Cadastro ----------------------------------------------------------

    async def create_user(self, *, email: str, password: str, full_name: str, role: Role) -> User:
        return await self._users.create(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
        )

    # --- Interno -----------------------------------------------------------

    async def _issue_tokens(
        self, user: User, *, user_agent: str | None, ip_address: str | None
    ) -> TokenPair:
        access_token, expires_at = create_access_token(
            self._settings, user_id=user.id, role=user.role.value
        )

        refresh_token = generate_refresh_token()
        await self._refresh_tokens.create(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=refresh_token_expiry(self._settings),
            user_agent=user_agent,
            ip_address=ip_address,
        )

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int((expires_at - datetime.now(UTC)).total_seconds()),
        )
