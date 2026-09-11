"""Documentos contra PostgreSQL real.

O service de documentos depende de constraints (UNIQUE de checksum, FKs com RESTRICT) e
de comportamento transacional. Um repositorio em memoria nao tem nenhum dos dois, entao
testar aqui nao e preciosismo: e o unico lugar onde essas regras existem de fato.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from io import BytesIO

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Environment, Settings
from app.core.errors import NotFoundError
from app.db.session import create_engine, create_session_factory
from app.modules.documents.models import DocumentStatus
from app.modules.documents.repository import (
    DocumentFilters,
    DocumentRepository,
    DocumentVersionRepository,
)
from app.modules.documents.service import DocumentService, DuplicateDocumentError
from app.modules.documents.validation import UnsupportedFileTypeError
from app.modules.ingestion.models import JobStatus
from app.modules.ingestion.repository import ProcessingJobRepository
from app.modules.users.models import Role, User
from tests.fakes import FakeStorage

pytestmark = pytest.mark.integration

DATABASE_URL = os.getenv("DATABASE_URL", "")

requires_db = pytest.mark.skipif(
    not DATABASE_URL or "localhost" in DATABASE_URL,
    reason="defina DATABASE_URL apontando para um PostgreSQL real",
)


def pdf(marcador: str = "") -> BytesIO:
    """PDF minimo. O marcador torna o checksum unico entre testes."""
    return BytesIO(f"%PDF-1.7\n{marcador}\ntrailer\n%%EOF\n".encode())


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        app_env=Environment.TEST,
        jwt_secret_key="segredo-de-teste-com-tamanho-suficiente",
    )


@pytest_asyncio.fixture
async def session_factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(settings)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


def build_service(session: AsyncSession, storage: FakeStorage) -> DocumentService:
    return DocumentService(
        documents=DocumentRepository(session),
        versions=DocumentVersionRepository(session),
        jobs=ProcessingJobRepository(session),
        storage=storage,  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def admin(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[uuid.UUID]:
    """Admin descartavel. Ao final remove tudo que ele criou, em ordem de dependencia."""
    async with session_factory() as session:
        user = User(
            email=f"admin-{uuid.uuid4().hex[:12]}@bancoexemplo.com.br",
            password_hash="x",
            full_name="Admin de Teste",
            role=Role.ADMIN,
        )
        session.add(user)
        await session.commit()
        user_id = user.id

    yield user_id

    async with session_factory() as session:
        await session.execute(
            text("""
                DELETE FROM processing_jobs WHERE document_version_id IN (
                    SELECT dv.id FROM document_versions dv
                    JOIN documents d ON d.id = dv.document_id
                    WHERE d.uploaded_by = :id)
            """),
            {"id": user_id},
        )
        await session.execute(
            text("""
                DELETE FROM document_versions WHERE document_id IN (
                    SELECT id FROM documents WHERE uploaded_by = :id)
            """),
            {"id": user_id},
        )
        await session.execute(
            text("DELETE FROM documents WHERE uploaded_by = :id"), {"id": user_id}
        )
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await session.commit()


# --- Upload ----------------------------------------------------------------


@requires_db
async def test_upload_cria_documento_versao_e_job(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage, admin: uuid.UUID
) -> None:
    async with session_factory() as session:
        documento, versao = await build_service(session, storage).create_document(
            title="Manual de Cadastro",
            description="Procedimentos de abertura e manutencao",
            category="Cadastro",
            filename="manual.pdf",
            stream=pdf("cadastro"),
            uploaded_by=admin,
        )
        await session.commit()
        doc_id, ver_id = documento.id, versao.id

    async with session_factory() as session:
        jobs = await session.execute(
            text("SELECT status, attempts FROM processing_jobs WHERE document_version_id = :id"),
            {"id": ver_id},
        )
        status_job, tentativas = jobs.one()

    # A versao nasce PENDING e nao corrente: nada entra na busca antes de ser indexado.
    assert versao.status is DocumentStatus.PENDING
    assert versao.is_current is False
    assert versao.version_number == 1
    # Versao e job na mesma transacao (ADR-0004): nao existe versao sem quem a processe.
    assert status_job == JobStatus.PENDING.value
    assert tentativas == 0
    assert storage.objetos[versao.storage_key].startswith(b"%PDF")
    assert str(doc_id) in versao.storage_key


@requires_db
async def test_arquivo_duplicado_e_recusado(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage, admin: uuid.UUID
) -> None:
    """O checksum barra o re-upload antes de gastar storage e, na Fase 5, embeddings."""
    conteudo = "identico"

    async with session_factory() as session:
        await build_service(session, storage).create_document(
            title="Primeiro",
            description=None,
            category=None,
            filename="a.pdf",
            stream=pdf(conteudo),
            uploaded_by=admin,
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(DuplicateDocumentError) as erro:
            await build_service(session, storage).create_document(
                title="Segundo",
                description=None,
                category=None,
                filename="b.pdf",
                stream=pdf(conteudo),
                uploaded_by=admin,
            )

    assert "document_id" in erro.value.details


@requires_db
async def test_formato_invalido_nao_grava_nada(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage, admin: uuid.UUID
) -> None:
    """A validacao acontece antes de qualquer escrita."""
    async with session_factory() as session:
        with pytest.raises(UnsupportedFileTypeError):
            await build_service(session, storage).create_document(
                title="Executavel disfarcado",
                description=None,
                category=None,
                filename="manual.pdf",
                stream=BytesIO(b"MZ\x90\x00" + b"\x00" * 128),
                uploaded_by=admin,
            )

    assert storage.objetos == {}


@requires_db
async def test_falha_de_storage_nao_deixa_registro_orfao(
    session_factory: async_sessionmaker[AsyncSession], admin: uuid.UUID
) -> None:
    """A razao de gravar no storage ANTES do banco.

    Na ordem inversa, uma falha aqui deixaria um documento listado que quebraria ao ser
    aberto. Assim, a transacao e revertida e nada fica.
    """
    falhando = FakeStorage(falhar_no_put=True)

    async with session_factory() as session:
        with pytest.raises(Exception, match="armazenar"):
            await build_service(session, falhando).create_document(
                title="Vai falhar",
                description=None,
                category=None,
                filename="x.pdf",
                stream=pdf("falha-storage"),
                uploaded_by=admin,
            )
        await session.rollback()

    async with session_factory() as session:
        total = await session.execute(
            text("SELECT count(*) FROM documents WHERE uploaded_by = :id AND title = 'Vai falhar'"),
            {"id": admin},
        )
        assert total.scalar_one() == 0


# --- Versoes ---------------------------------------------------------------


@requires_db
async def test_nova_versao_nao_derruba_a_corrente(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage, admin: uuid.UUID
) -> None:
    """A v1 continua servindo a busca ate a v2 terminar de processar (ADR-0005)."""
    async with session_factory() as session:
        documento, v1 = await build_service(session, storage).create_document(
            title="Politica de KYC",
            description=None,
            category="Compliance",
            filename="kyc.pdf",
            stream=pdf("kyc-v1"),
            uploaded_by=admin,
        )
        await session.commit()
        doc_id, v1_id = documento.id, v1.id

    # Simula o fim do processamento da v1 (Fase 5 fara isso).
    async with session_factory() as session:
        await session.execute(
            text("UPDATE document_versions SET status='READY', is_current=true WHERE id = :id"),
            {"id": v1_id},
        )
        await session.commit()

    async with session_factory() as session:
        v2 = await build_service(session, storage).add_version(
            document_id=doc_id, filename="kyc-atualizado.pdf", stream=pdf("kyc-v2")
        )
        await session.commit()
        assert v2.version_number == 2
        assert v2.is_current is False

    async with session_factory() as session:
        corrente = await session.execute(
            text(
                "SELECT version_number FROM document_versions WHERE document_id=:id AND is_current"
            ),
            {"id": doc_id},
        )
        assert corrente.scalar_one() == 1


@requires_db
async def test_apenas_uma_versao_corrente_e_permitida(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage, admin: uuid.UUID
) -> None:
    """A invariante de ADR-0005 imposta pelo indice parcial unico."""
    from sqlalchemy.exc import IntegrityError

    async with session_factory() as session:
        documento, v1 = await build_service(session, storage).create_document(
            title="Circular 3.978",
            description=None,
            category="Normativos",
            filename="circular.pdf",
            stream=pdf("circular-v1"),
            uploaded_by=admin,
        )
        await session.commit()
        doc_id, v1_id = documento.id, v1.id

    async with session_factory() as session:
        v2 = await build_service(session, storage).add_version(
            document_id=doc_id, filename="c2.pdf", stream=pdf("circular-v2")
        )
        await session.commit()
        v2_id = v2.id

    async with session_factory() as session:
        await session.execute(
            text("UPDATE document_versions SET is_current=true WHERE id=:id"), {"id": v1_id}
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text("UPDATE document_versions SET is_current=true WHERE id=:id"), {"id": v2_id}
            )
            await session.commit()


# --- Listagem e exclusao ---------------------------------------------------


@requires_db
async def test_listagem_filtra_por_titulo(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage, admin: uuid.UUID
) -> None:
    marcador = uuid.uuid4().hex[:8]

    async with session_factory() as session:
        servico = build_service(session, storage)
        for nome in (f"Manual PIX {marcador}", f"Procedimento TED {marcador}"):
            await servico.create_document(
                title=nome,
                description=None,
                category="Pagamentos",
                filename="d.pdf",
                stream=pdf(nome),
                uploaded_by=admin,
            )
        await session.commit()

    async with session_factory() as session:
        pagina = await build_service(session, storage).list_documents(
            filtros=DocumentFilters(termo=f"PIX {marcador}"), pagina=1, tamanho=20
        )

    assert pagina.total == 1
    assert marcador in pagina.itens[0].title


@requires_db
async def test_documento_excluido_some_da_listagem_mas_nao_do_banco(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage, admin: uuid.UUID
) -> None:
    """Soft delete: as citacoes historicas precisam continuar resolviveis (ADR-0005)."""
    async with session_factory() as session:
        documento, _ = await build_service(session, storage).create_document(
            title=f"Para excluir {uuid.uuid4().hex[:8]}",
            description=None,
            category=None,
            filename="d.pdf",
            stream=pdf("excluir"),
            uploaded_by=admin,
        )
        await session.commit()
        doc_id = documento.id

    async with session_factory() as session:
        await build_service(session, storage).delete_document(doc_id)
        await session.commit()

    async with session_factory() as session:
        servico = build_service(session, storage)
        with pytest.raises(NotFoundError):
            await servico.get_document(doc_id)

        existe = await session.execute(
            text("SELECT deleted_at IS NOT NULL FROM documents WHERE id = :id"), {"id": doc_id}
        )
        assert existe.scalar_one() is True

    # O arquivo tambem permanece: uma citacao antiga ainda precisa abrir a fonte.
    assert storage.objetos


@requires_db
async def test_excluir_documento_inexistente_e_404(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError):
            await build_service(session, storage).delete_document(uuid.uuid4())


# --- Reprocessamento -------------------------------------------------------


@requires_db
async def test_reprocessar_enfileira_novo_job_e_limpa_o_erro(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage, admin: uuid.UUID
) -> None:
    """Caminho de recuperacao de um FAILED."""
    async with session_factory() as session:
        documento, versao = await build_service(session, storage).create_document(
            title=f"Falhou {uuid.uuid4().hex[:8]}",
            description=None,
            category=None,
            filename="d.pdf",
            stream=pdf("reprocessar"),
            uploaded_by=admin,
        )
        await session.commit()
        doc_id, ver_id = documento.id, versao.id

    async with session_factory() as session:
        await session.execute(
            text("""
                UPDATE document_versions
                SET status='FAILED', error_code='NO_TEXT_LAYER', error_detail='PDF sem texto'
                WHERE id = :id
            """),
            {"id": ver_id},
        )
        await session.commit()

    async with session_factory() as session:
        await build_service(session, storage).reprocess(doc_id)
        await session.commit()

    async with session_factory() as session:
        estado = await session.execute(
            text("SELECT status, error_code, error_detail FROM document_versions WHERE id=:id"),
            {"id": ver_id},
        )
        situacao, codigo, detalhe = estado.one()

        jobs = await session.execute(
            text("SELECT count(*) FROM processing_jobs WHERE document_version_id=:id"),
            {"id": ver_id},
        )

    assert situacao == DocumentStatus.PENDING.value
    assert codigo is None
    assert detalhe is None
    assert jobs.scalar_one() == 2  # o original mais o reenfileirado


# --- Fila ------------------------------------------------------------------


@requires_db
async def test_claim_reivindica_um_job_por_vez(
    session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage, admin: uuid.UUID
) -> None:
    """`FOR UPDATE SKIP LOCKED` e o que faz a fila funcionar com varios workers."""
    async with session_factory() as session:
        _, versao = await build_service(session, storage).create_document(
            title=f"Para a fila {uuid.uuid4().hex[:8]}",
            description=None,
            category=None,
            filename="d.pdf",
            stream=pdf(f"fila-{uuid.uuid4().hex}"),
            uploaded_by=admin,
        )
        await session.commit()
        version_id = versao.id

    async with session_factory() as session:
        # Restrito a propria versao: o banco e compartilhado com o acervo real, e
        # um claim irrestrito tomaria (e deixaria RUNNING) um job de verdade.
        job = await ProcessingJobRepository(session).claim(version_ids={version_id})
        assert job is not None
        assert job.status is JobStatus.RUNNING
        assert job.attempts == 1
        assert job.started_at is not None
        await session.commit()
