"""Migration x modelos.

Sem banco, `alembic check` (que compara o schema real com o metadata) nao pode rodar.
Estes testes cobrem a mesma falha por outro caminho: geram o SQL da migration em modo
offline e comparam com o DDL que o metadata produz.

A divergencia que isto pega e a mais perigosa da fase: adicionar uma coluna ao modelo e
esquecer a migration. O codigo funciona em desenvolvimento (onde o banco foi criado a
partir do metadata) e quebra em producao (onde foi criado pela migration).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.registry import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def migration_sql() -> str:
    """SQL completo da migration, em modo offline (sem conexao)."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, f"alembic falhou:\n{result.stderr}"
    return result.stdout


@pytest.fixture(scope="module")
def metadata_sql() -> str:
    dialect = postgresql.dialect()
    parts: list[str] = []
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)))
        for index in table.indexes:
            parts.append(str(CreateIndex(index).compile(dialect=dialect)))
    return "\n".join(parts)


def _tables(sql: str) -> set[str]:
    return set(re.findall(r"CREATE TABLE (\w+)", sql)) - {"alembic_version"}


def _columns(sql: str) -> set[tuple[str, str]]:
    """Pares (tabela, coluna) extraidos dos blocos CREATE TABLE."""
    found: set[tuple[str, str]] = set()
    for match in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\)", sql, re.DOTALL):
        table, body = match.group(1), match.group(2)
        if table == "alembic_version":
            continue
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            # Linhas de constraint nao sao colunas.
            if not line or line.startswith(("CONSTRAINT", "PRIMARY KEY", "FOREIGN KEY")):
                continue
            found.add((table, line.split()[0]))
    return found


def _constraint_names(sql: str) -> set[str]:
    return set(re.findall(r"CONSTRAINT (\w+)", sql)) - {"alembic_version_pkc"}


def _index_names(sql: str) -> set[str]:
    return set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+)", sql))


def test_migration_cria_as_mesmas_tabelas(migration_sql: str, metadata_sql: str) -> None:
    assert _tables(migration_sql) == _tables(metadata_sql)


def test_migration_cria_as_mesmas_colunas(migration_sql: str, metadata_sql: str) -> None:
    da_migration = _columns(migration_sql)
    do_metadata = _columns(metadata_sql)

    faltando = do_metadata - da_migration
    sobrando = da_migration - do_metadata
    assert not faltando, f"colunas no modelo mas ausentes na migration: {sorted(faltando)}"
    assert not sobrando, f"colunas na migration mas ausentes no modelo: {sorted(sobrando)}"


def test_migration_cria_as_mesmas_constraints(migration_sql: str, metadata_sql: str) -> None:
    assert _constraint_names(migration_sql) == _constraint_names(metadata_sql)


def test_migration_cria_os_mesmos_indices(migration_sql: str, metadata_sql: str) -> None:
    assert _index_names(migration_sql) == _index_names(metadata_sql)


def test_extensoes_criadas_antes_das_tabelas(migration_sql: str) -> None:
    """VECTOR e CITEXT nao existem como tipo antes do CREATE EXTENSION."""
    primeira_tabela = migration_sql.index("CREATE TABLE users")
    for extensao in ("vector", "pg_trgm", "citext"):
        posicao = migration_sql.index(f"CREATE EXTENSION IF NOT EXISTS {extensao}")
        assert posicao < primeira_tabela, f"extensao {extensao} criada tarde demais"


def test_enums_criados_antes_das_tabelas(migration_sql: str) -> None:
    primeira_tabela = migration_sql.index("CREATE TABLE users")
    for tipo in ("user_role", "doc_status", "job_status", "query_status"):
        posicao = migration_sql.index(f"CREATE TYPE {tipo}")
        assert posicao < primeira_tabela, f"tipo {tipo} criado tarde demais"


def test_coluna_tsv_usa_to_tsvector_de_dois_argumentos(migration_sql: str) -> None:
    """A variante de um argumento e apenas STABLE e o PostgreSQL a rejeita aqui."""
    assert (
        "tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('portuguese', content)) STORED"
        in migration_sql
    )


def test_indice_hnsw_usa_operador_de_cosseno(migration_sql: str) -> None:
    """Um indice com o operador errado nao falha: apenas nunca e usado pelo planner."""
    assert "USING hnsw (embedding vector_cosine_ops)" in migration_sql, (
        "indice vetorial ausente ou com operador incompativel com a busca"
    )


def test_apenas_uma_versao_corrente_por_documento(migration_sql: str) -> None:
    """Invariante de ADR-0005, garantida pelo banco e nao apenas por codigo."""
    assert (
        "CREATE UNIQUE INDEX uq_document_versions_current "
        "ON document_versions (document_id) WHERE is_current" in migration_sql
    )


def test_downgrade_remove_os_tipos_enum() -> None:
    """Sem DROP TYPE, um downgrade seguido de upgrade falha com "type already exists"."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "head:base", "--sql"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    for tipo in (
        "user_role",
        "doc_status",
        "job_status",
        "job_type",
        "query_status",
        "feedback_rating",
        "feedback_reason",
    ):
        assert f"DROP TYPE {tipo}" in result.stdout


def test_downgrade_remove_todas_as_tabelas(metadata_sql: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "head:base", "--sql"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    removidas = set(re.findall(r"DROP TABLE (\w+)", result.stdout))
    assert removidas == _tables(metadata_sql)
