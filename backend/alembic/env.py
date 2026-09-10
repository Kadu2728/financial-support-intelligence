"""Ambiente de migrations.

A URL vem de `Settings`, nunca do alembic.ini: uma unica fonte de verdade para a
configuracao de banco, e nenhuma credencial em arquivo versionado.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.db.registry import Base
from app.db.session import _connect_args

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", str(get_settings().database_url))


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Mantem fora do autogenerate o que nao pertence a aplicacao.

    Sem isto, o autogenerate tenta remover as tabelas internas de extensoes instaladas
    no mesmo schema.
    """
    if type_ == "table" and name is not None:
        return name not in {"spatial_ref_sys"}
    return True


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        # Detecta alteracao de tipo de coluna. Desligado por padrao no Alembic, o que
        # faz uma mudanca de VARCHAR(128) para VARCHAR(256) passar em silencio.
        compare_type=True,
        compare_server_default=True,
        # Sem isto, constraints e indices nomeados pela convencao de Base.metadata
        # geram diffs espurios a cada autogenerate.
        render_as_batch=False,
        # Cria os tipos ENUM antes das tabelas que os usam.
        transaction_per_migration=True,
    )


def run_migrations_offline() -> None:
    """Modo offline: gera o SQL sem conectar.

    `alembic upgrade head --sql` usa este caminho. E como a migration e revisada antes
    de existir um banco para aplicar.
    """
    _configure(url=config.get_main_option("sqlalchemy.url"))
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # Mesmos ajustes do engine da aplicacao: TLS reativado (o `sslmode` da URL e
        # removido por ser opcao do libpq) e cache de prepared statements desligado
        # por causa do pooler. Ver app/db/session.py.
        connect_args=_connect_args(get_settings()),
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
