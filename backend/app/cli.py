"""Comandos administrativos.

Existe por um motivo concreto: o cadastro de usuarios exige um ADMIN autenticado, e o
primeiro ADMIN nao tem quem o crie. Este e o unico caminho para resolver isso.

    .venv/Scripts/python -m app.cli create-admin --email a@b.com --name "Nome"

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

    args = parser.parse_args(argv)
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
