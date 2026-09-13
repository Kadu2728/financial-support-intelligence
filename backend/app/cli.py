"""Comandos administrativos.

Existe por um motivo concreto: o cadastro de usuarios exige um ADMIN autenticado, e o
primeiro ADMIN nao tem quem o crie. Este e o unico caminho para resolver isso.

    .venv/Scripts/python -m app.cli create-admin --email a@b.com --name "Nome"
    .venv/Scripts/python -m app.cli process-queue     # esvazia a fila de ingestao
    .venv/Scripts/python -m app.cli reindex-stale     # re-embeda apos troca de modelo

A senha e lida de forma interativa (`getpass`), nunca por argumento: argumentos de
linha de comando ficam no historico do shell e aparecem na lista de processos.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.security import hash_password

# O registry precisa ser importado antes de qualquer uso do ORM: os relationships sao
# declarados por NOME (`Mapped[list[RefreshToken]]`) e o SQLAlchemy so os resolve se a
# classe ja estiver registrada. Importar apenas `User` aqui levanta
# "expression 'RefreshToken' failed to locate a name" na primeira query.
from app.db import registry as _registry  # noqa: F401
from app.db.session import create_engine, create_session_factory
from app.modules.users.models import Role
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import CreateUserRequest


async def _create_user(email: str, full_name: str, password: str, role: Role) -> int:
    try:
        dados = CreateUserRequest(email=email, password=password, full_name=full_name, role=role)
    except ValidationError as exc:
        for erro in exc.errors():
            campo = ".".join(str(p) for p in erro["loc"])
            print(f"  {campo}: {erro['msg']}", file=sys.stderr)
        return 1

    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            repo = UserRepository(session)

            if await repo.get_by_email(dados.email) is not None:
                print(f"E-mail ja cadastrado: {dados.email}", file=sys.stderr)
                return 1

            user = await repo.create(
                email=dados.email,
                password_hash=hash_password(dados.password),
                full_name=dados.full_name,
                role=dados.role,
            )
            await session.commit()
            print(f"Criado: {user.email}  papel={user.role.value}  id={user.id}")
            return 0
    finally:
        await engine.dispose()


async def _process_queue() -> int:
    """Esvazia a fila de ingestao e sai. Util em dev e para indexar um acervo inicial
    sem esperar o polling do worker embutido na API."""
    from app.integrations.gemini.client import GeminiClient
    from app.integrations.storage.factory import build_storage
    from app.modules.ingestion.worker import IngestionWorker

    settings = get_settings()
    if not settings.gemini_configured:
        print("GEMINI_API_KEY nao configurada em backend/.env.", file=sys.stderr)
        return 1

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    gemini = GeminiClient(settings)
    try:
        worker = IngestionWorker(
            settings=settings,
            session_factory=session_factory,
            storage=build_storage(settings, session_factory),
            embeddings=gemini,
        )
        await worker.recover_stale()
        processados = 0
        while await worker.run_once():
            processados += 1
        print(f"Jobs processados: {processados}")
        return 0
    finally:
        await gemini.aclose()
        await engine.dispose()


async def _reindex_stale() -> int:
    """Re-enfileira versoes cujos chunks foram gerados por outro modelo de embedding.

    Vetores de modelos diferentes no mesmo indice produzem ranking sem significado,
    sem nenhum erro visivel. `embedding_model` e gravado por chunk exatamente para
    que este comando saiba o que regenerar apos uma troca de modelo.
    """
    from sqlalchemy import text

    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            versoes = (
                (
                    await session.execute(
                        text("""
                        SELECT DISTINCT dv.id
                        FROM document_versions dv
                        JOIN document_chunks c ON c.document_version_id = dv.id
                        WHERE dv.is_current AND c.embedding_model <> :modelo
                    """),
                        {"modelo": settings.gemini_embedding_model},
                    )
                )
                .scalars()
                .all()
            )

            for version_id in versoes:
                await session.execute(
                    text("""
                        INSERT INTO processing_jobs
                            (id, document_version_id, job_type, status, attempts, max_attempts)
                        VALUES (gen_random_uuid(), :id, 'INGEST', 'PENDING', 0, 3)
                    """),
                    {"id": version_id},
                )
            await session.commit()
        alvo = settings.gemini_embedding_model
        print(f"Versoes re-enfileiradas: {len(versoes)} (modelo alvo: {alvo})")
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

    criar = sub.add_parser("create-admin", help="Cria um usuario ADMIN")
    criar.add_argument("--email", required=True)
    criar.add_argument("--name", required=True, dest="full_name")
    criar.add_argument(
        "--role",
        default=Role.ADMIN.value,
        choices=[papel.value for papel in Role],
    )
    sub.add_parser("process-queue", help="Processa todos os jobs de ingestao pendentes")
    sub.add_parser("reindex-stale", help="Re-enfileira versoes com embeddings de outro modelo")

    args = parser.parse_args(argv)

    if args.comando == "process-queue":
        return asyncio.run(_process_queue())
    if args.comando == "reindex-stale":
        return asyncio.run(_reindex_stale())

    senha = _ler_senha()
    if senha is None:
        return 1
    return asyncio.run(_create_user(args.email, args.full_name, senha, Role(args.role)))


def _ler_senha() -> str | None:
    """Le a senha sem que ela apareca em historico de shell ou lista de processos.

    `FSI_ADMIN_PASSWORD` existe para provisionamento automatizado (CI, container de
    bootstrap), onde nao ha terminal interativo. Variavel de ambiente e pior que
    `getpass` e melhor que argumento de linha de comando: nao fica no historico nem em
    `ps`, mas e herdada por processos filhos — por isso o modo interativo continua
    sendo o padrao.
    """
    do_ambiente = os.environ.get("FSI_ADMIN_PASSWORD")
    if do_ambiente:
        print("Usando a senha de FSI_ADMIN_PASSWORD.", file=sys.stderr)
        return do_ambiente

    senha = getpass.getpass("Senha: ")
    if senha != getpass.getpass("Confirme a senha: "):
        print("As senhas nao coincidem.", file=sys.stderr)
        return None
    return senha


if __name__ == "__main__":
    raise SystemExit(main())
