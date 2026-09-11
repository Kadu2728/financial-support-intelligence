"""Invariantes de design do schema.

Estes testes nao verificam se o SQL e valido — `test_migrations.py` cobre isso. Eles
protegem decisoes que sao facil de desfazer sem perceber: uma FK sem `ondelete`, um
relationship sem `lazy="raise"`, um enum que divergiu entre Python e banco.

Sao as regressoes que passam em code review porque cada uma, isolada, parece inofensiva.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import RelationshipProperty, class_mapper, configure_mappers

from app.db.base import EMBEDDING_DIM, Base
from app.db.registry import (
    Answer,
    Citation,
    Document,
    DocumentChunk,
    DocumentVersion,
    Feedback,
    ProcessingJob,
    Query,
    RefreshToken,
    User,
)
from app.modules.documents.models import DocumentStatus
from app.modules.feedback.models import FeedbackRating, FeedbackReason
from app.modules.ingestion.models import JobStatus, JobType
from app.modules.queries.models import QueryStatus
from app.modules.users.models import Role

TODOS_OS_MODELOS = [
    Answer,
    Citation,
    Document,
    DocumentChunk,
    DocumentVersion,
    Feedback,
    ProcessingJob,
    Query,
    RefreshToken,
    User,
]


def test_toda_foreign_key_declara_ondelete() -> None:
    """`ondelete` implicito e NO ACTION, que so falha quando alguem tenta apagar algo.

    Tornar a intencao explicita e o que torna revisavel a diferenca entre "leve junto"
    (CASCADE) e "proteja este vinculo" (RESTRICT).
    """
    sem_ondelete = [
        f"{table.name}.{fk.parent.name}"
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.ondelete is None
    ]

    assert not sem_ondelete, f"FKs sem ondelete explicito: {sorted(sem_ondelete)}"


def test_citacao_nunca_fica_orfa() -> None:
    """RESTRICT no chunk citado sustenta a rastreabilidade (ADR-0005, ADR-0008).

    Se virasse CASCADE, apagar um documento apagaria em silencio as citacoes das
    respostas historicas — e o historico passaria a exibir respostas sem fonte.
    """
    tabela = Citation.__table__
    por_coluna = {fk.parent.name: fk.ondelete for fk in tabela.foreign_keys}

    assert por_coluna["document_chunk_id"] == "RESTRICT"
    assert por_coluna["document_version_id"] == "RESTRICT"
    # A citacao em si morre com a resposta: sem resposta, nao ha o que citar.
    assert por_coluna["answer_id"] == "CASCADE"


def test_documento_nao_e_apagado_junto_com_o_usuario() -> None:
    """O acervo pertence a organizacao, nao a quem fez o upload."""
    por_coluna = {fk.parent.name: fk.ondelete for fk in Document.__table__.foreign_keys}

    assert por_coluna["uploaded_by"] == "RESTRICT"


def test_chunks_morrem_com_a_versao() -> None:
    """Uma versao sem chunks e coerente; chunks sem versao sao lixo indexavel."""
    por_coluna = {fk.parent.name: fk.ondelete for fk in DocumentChunk.__table__.foreign_keys}

    assert por_coluna["document_version_id"] == "CASCADE"


@pytest.mark.parametrize("modelo", TODOS_OS_MODELOS, ids=lambda m: m.__name__)
def test_relationships_usam_lazy_raise(modelo: type) -> None:
    """Em SQLAlchemy async, um lazy-load acidental levanta MissingGreenlet em runtime.

    Com `lazy="raise"` o erro aparece no teste, nao em producao, e a correcao e sempre
    a mesma: carregar explicitamente com selectinload.
    """
    permissivos = [
        f"{modelo.__name__}.{rel.key}"
        for rel in class_mapper(modelo).relationships
        if isinstance(rel, RelationshipProperty) and rel.lazy != "raise"
    ]

    assert not permissivos, f"relationships sem lazy='raise': {permissivos}"


@pytest.mark.parametrize(
    ("enum_python", "nome_no_banco"),
    [
        (Role, "user_role"),
        (DocumentStatus, "doc_status"),
        (JobStatus, "job_status"),
        (JobType, "job_type"),
        (QueryStatus, "query_status"),
        (FeedbackRating, "feedback_rating"),
        (FeedbackReason, "feedback_reason"),
    ],
    ids=lambda v: v if isinstance(v, str) else v.__name__,
)
def test_enums_do_python_batem_com_os_do_banco(enum_python: type, nome_no_banco: str) -> None:
    """Divergencia aqui grava um valor que o codigo nunca consegue ler de volta."""
    do_banco: set[str] = set()
    for tabela in Base.metadata.tables.values():
        for coluna in tabela.columns:
            if isinstance(coluna.type, SAEnum) and coluna.type.name == nome_no_banco:
                do_banco = set(coluna.type.enums)

    assert do_banco, f"nenhuma coluna usa o tipo {nome_no_banco}"
    assert do_banco == {membro.value for membro in enum_python}


def test_membros_de_enum_tem_nome_igual_ao_valor() -> None:
    """`values_callable` grava o valor; o codigo costuma referenciar pelo nome.

    Enquanto os dois coincidem, renomear um membro nao muda o dado gravado em silencio.
    """
    for enum_python in (
        Role,
        DocumentStatus,
        JobStatus,
        JobType,
        QueryStatus,
        FeedbackRating,
        FeedbackReason,
    ):
        divergentes = [m.name for m in enum_python if m.name != m.value]
        assert not divergentes, f"{enum_python.__name__}: {divergentes}"


def test_embeddings_de_chunk_e_de_pergunta_tem_a_mesma_dimensao() -> None:
    """Pergunta e chunk sao comparados por distancia: dimensoes diferentes nao casam.

    O erro nem sempre e claro — dependendo do caminho, o resultado e apenas um ranking
    sem sentido.
    """
    dim_chunk = DocumentChunk.__table__.c.embedding.type.dim
    dim_query = Query.__table__.c.embedding.type.dim

    assert dim_chunk == dim_query == EMBEDDING_DIM


def test_hnsw_suporta_a_dimensao_escolhida() -> None:
    """HNSW no pgvector indexa ate 2000 dimensoes.

    Acima disso o CREATE INDEX falha — e a busca vetorial vira scan sequencial.
    """
    assert EMBEDDING_DIM <= 2000


def test_toda_tabela_tem_created_at() -> None:
    """Sem timestamp de criacao, nenhuma serie temporal do Intelligence e possivel."""
    sem_created_at = [
        tabela.name
        for tabela in Base.metadata.tables.values()
        if "created_at" not in tabela.columns
    ]

    assert not sem_created_at


def test_convencao_de_nomes_aplicada_a_todas_as_constraints() -> None:
    """Nomes deterministicos sao o que faz o downgrade encontrar o que remover."""
    prefixos = ("pk_", "fk_", "uq_", "ck_", "ix_")
    fora_do_padrao = [
        constraint.name
        for tabela in Base.metadata.tables.values()
        for constraint in tabela.constraints
        if constraint.name and not str(constraint.name).startswith(prefixos)
    ]

    assert not fora_do_padrao, f"constraints fora da convencao: {fora_do_padrao}"


def test_uma_unica_versao_corrente_por_documento() -> None:
    """A invariante de ADR-0005 vive no banco, nao apenas no service."""
    indices = {ix.name: ix for ix in DocumentVersion.__table__.indexes}
    corrente = indices.get("uq_document_versions_current")

    assert corrente is not None, "indice de versao corrente ausente"
    assert corrente.unique, "sem UNIQUE, duas versoes correntes duplicam a busca"
    assert corrente.dialect_options["postgresql"]["where"] is not None, (
        "sem clausula parcial, o indice impediria mais de uma versao por documento"
    )


def test_feedback_e_unico_por_usuario_e_consulta() -> None:
    """Sem isto, um usuario poderia votar varias vezes e distorcer a metrica."""
    uniques = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in Feedback.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("query_id", "user_id") in uniques


def test_answer_e_um_para_um_com_query() -> None:
    assert Answer.__table__.c.query_id.unique is True


def test_todos_os_mappers_configuram() -> None:
    """Relationships sao declarados por NOME e resolvidos so na primeira query.

    Se um modelo referenciado nao tiver sido importado, o erro aparece em runtime —
    e nao no entrypoint principal, que importa tudo por tabela, mas em um script ou
    worker que importa apenas parte dos modelos. Foi exatamente assim que o CLI
    quebrou com "expression 'RefreshToken' failed to locate a name".

    `configure_mappers` forca a resolucao agora, no teste.
    """
    configure_mappers()
