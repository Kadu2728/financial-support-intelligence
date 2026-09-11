"""Repositories em memoria.

Permitem testar a regra de negocio do `AuthService` — rotacao, deteccao de reuso,
resposta a conta desativada — sem banco. O que estes fakes NAO cobrem (constraints,
CITEXT, transacoes) fica para os testes marcados `integration`, que rodam contra
PostgreSQL real.

A fronteira e honesta: aqui se testa a decisao, la se testa a persistencia.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.integrations.storage.base import ObjectNotFound, StorageError
from app.modules.auth.models import RefreshToken
from app.modules.users.models import Role, User


class FakeUserRepository:
    def __init__(self, users: list[User] | None = None) -> None:
        self._users: dict[uuid.UUID, User] = {u.id: u for u in (users or [])}
        self.password_updates: list[tuple[uuid.UUID, str]] = []
        self.logins_registrados: list[uuid.UUID] = []

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        # CITEXT no banco; aqui a normalizacao e explicita.
        alvo = email.casefold()
        return next((u for u in self._users.values() if u.email.casefold() == alvo), None)

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        full_name: str,
        role: Role = Role.ANALYST,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            role=role,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self._users[user.id] = user
        return user

    async def touch_last_login(self, user_id: uuid.UUID) -> None:
        self.logins_registrados.append(user_id)

    async def update_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None:
        self.password_updates.append((user_id, password_hash))
        if user := self._users.get(user_id):
            user.password_hash = password_hash


class FakeRefreshTokenRepository:
    def __init__(self) -> None:
        self._tokens: dict[uuid.UUID, RefreshToken] = {}

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> RefreshToken:
        token = RefreshToken(
            id=uuid.uuid4(),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked_at=None,
            user_agent=user_agent,
            ip_address=ip_address,
            created_at=datetime.now(UTC),
        )
        self._tokens[token.id] = token
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return next((t for t in self._tokens.values() if t.token_hash == token_hash), None)

    async def revoke(self, token_id: uuid.UUID) -> None:
        token = self._tokens.get(token_id)
        if token is not None and token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        ativos = [t for t in self._tokens.values() if t.user_id == user_id and t.revoked_at is None]
        agora = datetime.now(UTC)
        for token in ativos:
            token.revoked_at = agora
        return len(ativos)

    # --- Auxiliares de teste ---

    @property
    def ativos(self) -> list[RefreshToken]:
        return [t for t in self._tokens.values() if t.revoked_at is None]

    @property
    def total(self) -> int:
        return len(self._tokens)


class FakeSession:
    """Sessao falsa que registra os commits.

    Existe para o commit da deteccao de reuso (ver AuthService.refresh). Contar os
    commits permite testar que ele acontece — mas nao substitui o teste de integracao,
    que e o unico capaz de provar que a revogacao sobrevive ao rollback real.
    """

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


class FakeStorage:
    """Storage em memoria, com falha injetavel.

    A injecao de falha existe para exercitar a ordem storage-antes-do-banco: e o unico
    jeito de verificar que uma falha de armazenamento nao deixa registro orfao.
    """

    def __init__(self, *, falhar_no_put: bool = False) -> None:
        self.objetos: dict[str, bytes] = {}
        self.falhar_no_put = falhar_no_put
        self.deletados: list[str] = []

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        if self.falhar_no_put:
            raise StorageError("falha simulada de armazenamento")
        self.objetos[key] = data

    async def get(self, key: str) -> bytes:
        try:
            return self.objetos[key]
        except KeyError as exc:
            raise ObjectNotFound(key) from exc

    async def delete(self, key: str) -> None:
        self.deletados.append(key)
        self.objetos.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objetos


class FakeEmbeddingClient:
    """Embeddings deterministicos por hashing de palavras.

    Cada palavra vai para uma posicao fixa do vetor (hash mod 768); o vetor final e
    normalizado. Dois textos que compartilham palavras ficam proximos em cosine —
    o suficiente para exercitar a busca, a fusao e o gate sem chamar o Gemini.
    Nao mede qualidade semantica; isso so o modelo real mede.
    """

    embedding_model = "fake-embedding-768"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.chamadas: list[tuple[int, str]] = []

    async def embed(self, textos: list[str], *, task_type: object) -> list[list[float]]:
        if self.fail:
            from app.integrations.gemini.client import GeminiError

            raise GeminiError("falha injetada")
        self.chamadas.append((len(textos), str(task_type)))
        return [embed_fake(t) for t in textos]


def embed_fake(texto: str, dimensoes: int = 768) -> list[float]:
    import hashlib
    import math
    import re

    vetor = [0.0] * dimensoes
    for palavra in re.findall(r"\w+", texto.lower()):
        if len(palavra) < 3:
            continue
        indice = int(hashlib.md5(palavra.encode(), usedforsecurity=False).hexdigest(), 16)
        vetor[indice % dimensoes] += 1.0
    norma = math.sqrt(sum(x * x for x in vetor))
    if norma == 0:
        vetor[0] = 1.0
        return vetor
    return [x / norma for x in vetor]


class FakeGenerationClient:
    """Devolve a resposta programada e registra o prompt recebido."""

    generation_model = "fake-generation"

    def __init__(self, resposta: dict[str, object] | None = None, *, fail: bool = False) -> None:
        self.resposta = resposta
        self.fail = fail
        self.prompts: list[tuple[str, str]] = []

    async def generate_json(
        self, *, system: str, user: str, response_schema: dict[str, object], temperature: float
    ) -> object:
        import json

        from app.integrations.gemini.client import GeminiError, GenerationResult

        self.prompts.append((system, user))
        if self.fail:
            raise GeminiError("falha injetada")
        return GenerationResult(
            text=json.dumps(self.resposta or {}),
            model=self.generation_model,
            prompt_tokens=100,
            completion_tokens=50,
            finish_reason="STOP",
        )
