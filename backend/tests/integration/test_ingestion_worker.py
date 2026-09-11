"""Worker de ingestao contra PostgreSQL real.

O que so o banco prova: a atomicidade READY+chunks+is_current, o indice parcial unico
de versao corrente, o claim com SKIP LOCKED e o estado do job apos cada tipo de falha.
"""

from __future__ import annotations

import uuid
from io import BytesIO

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.documents.models import DocumentStatus
from app.modules.documents.repository import DocumentRepository, DocumentVersionRepository
from app.modules.documents.service import DocumentService
from app.modules.ingestion.repository import ProcessingJobRepository
from app.modules.ingestion.worker import IngestionWorker
from app.modules.users.models import User
from tests.fakes import FakeEmbeddingClient, FakeStorage
from tests.integration.conftest import requires_db

pytestmark = pytest.mark.integration

MANUAL = """# Manual de Cadastro

## 1. Abertura de conta

Para abrir uma conta corrente o cliente precisa apresentar documento de identidade
com foto, CPF e comprovante de residencia emitido nos ultimos noventa dias. O
analista confere os dados no sistema e registra o protocolo de abertura. Quando o
cliente e pessoa juridica, o contrato social e o cartao CNPJ tambem sao exigidos, e
a conta so e liberada apos a validacao da equipe de prevencao a lavagem de dinheiro,
que tem prazo de dois dias uteis para concluir a analise documental.

## 2. Atualizacao cadastral

A atualizacao cadastral deve ser feita a cada vinte e quatro meses. O cliente pode
atualizar pelo aplicativo ou em agencia. Alteracoes de renda acima de cinco mil reais
exigem comprovante e aprovacao do gerente. Mudanca de endereco exige comprovante com
ate noventa dias de emissao. A atualizacao vencida bloqueia transferencias acima do
limite diario ate a regularizacao, e o analista deve orientar o cliente sobre o
canal mais rapido para concluir o procedimento.

## 3. Encerramento

O encerramento exige saldo zerado e ausencia de debitos pendentes. O prazo de
conclusao e de ate trinta dias uteis apos a solicitacao formal. Cartoes vinculados
sao cancelados no mesmo ato, e a fatura em aberto precisa ser quitada antes. O
cliente recebe o termo de encerramento por e-mail e pode solicitar a segunda via
pelo aplicativo durante cinco anos, conforme a politica de retencao de documentos.
"""


def build_worker(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    embeddings: FakeEmbeddingClient | None = None,
) -> IngestionWorker:
    return IngestionWorker(
        settings=settings,
        session_factory=session_factory,
        storage=storage,  # type: ignore[arg-type]
        embeddings=embeddings or FakeEmbeddingClient(),
    )


async def upload(
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
    *,
    conteudo: bytes,
    filename: str,
    titulo: str = "Manual de Cadastro",
) -> tuple[uuid.UUID, uuid.UUID]:
    async with session_factory() as session:
        service = DocumentService(
            documents=DocumentRepository(session),
            versions=DocumentVersionRepository(session),
            jobs=ProcessingJobRepository(session),
            storage=storage,  # type: ignore[arg-type]
        )
        documento, versao = await service.create_document(
            title=titulo,
            description=None,
            category="Cadastro",
            filename=filename,
            stream=BytesIO(conteudo),
            uploaded_by=admin.id,
        )
        await session.commit()
        return documento.id, versao.id


async def estado_versao(
    session_factory: async_sessionmaker[AsyncSession], version_id: uuid.UUID
) -> tuple[str, bool, int | None]:
    async with session_factory() as session:
        linha = (
            await session.execute(
                text(
                    "SELECT status, is_current, chunk_count FROM document_versions WHERE id = :id"
                ),
                {"id": version_id},
            )
        ).one()
        return str(linha[0]), bool(linha[1]), linha[2]


async def estado_job(
    session_factory: async_sessionmaker[AsyncSession], version_id: uuid.UUID
) -> tuple[str, int, str | None]:
    async with session_factory() as session:
        linha = (
            await session.execute(
                text(
                    "SELECT status, attempts, last_error FROM processing_jobs "
                    "WHERE document_version_id = :id ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": version_id},
            )
        ).one()
        return str(linha[0]), int(linha[1]), linha[2]


# --- Caminho feliz -------------------------------------------------------------


@requires_db
async def test_fila_vazia_devolve_false(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    # O banco e compartilhado com dados reais; restringir a um id inexistente
    # equivale a uma fila vazia sem tocar nos jobs dos outros.
    worker = build_worker(settings, session_factory, storage)
    assert await worker.run_once(version_ids={uuid.uuid4()}) is False


@requires_db
async def test_processa_markdown_ate_ready(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    _, version_id = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="manual.md"
    )
    embeddings = FakeEmbeddingClient()
    worker = build_worker(settings, session_factory, storage, embeddings)

    assert await worker.run_once(version_ids={version_id}) is True

    status, corrente, chunk_count = await estado_versao(session_factory, version_id)
    assert status == DocumentStatus.READY.value
    assert corrente is True
    assert chunk_count and chunk_count >= 1

    async with session_factory() as session:
        linhas = (
            await session.execute(
                text(
                    "SELECT chunk_index, section_path, content_tokens, embedding_model, "
                    "char_start, char_end, tsv IS NOT NULL "
                    "FROM document_chunks WHERE document_version_id = :id ORDER BY chunk_index"
                ),
                {"id": version_id},
            )
        ).all()

    assert len(linhas) == chunk_count
    assert [linha[0] for linha in linhas] == list(range(len(linhas)))
    assert all(linha[3] == "fake-embedding-768" for linha in linhas)
    assert all(linha[5] > linha[4] for linha in linhas)
    # A coluna gerada `tsv` e a perna lexical da busca: precisa existir sem que
    # ninguem a escreva.
    assert all(linha[6] for linha in linhas)
    # O section_path vem da hierarquia do Markdown.
    assert any(linha[1] and "Atualizacao cadastral" in linha[1] for linha in linhas)
    # Um lote so: o documento e menor que 64 chunks.
    assert len(embeddings.chamadas) == 1
    assert embeddings.chamadas[0][1].endswith("RETRIEVAL_DOCUMENT")

    job_status, tentativas, _ = await estado_job(session_factory, version_id)
    assert job_status == "COMPLETED"
    assert tentativas == 1


@requires_db
async def test_nova_versao_rebaixa_a_anterior(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    doc_id, v1 = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="v1.md"
    )
    worker = build_worker(settings, session_factory, storage)
    assert await worker.run_once(version_ids={v1}) is True

    async with session_factory() as session:
        service = DocumentService(
            documents=DocumentRepository(session),
            versions=DocumentVersionRepository(session),
            jobs=ProcessingJobRepository(session),
            storage=storage,  # type: ignore[arg-type]
        )
        versao2 = await service.add_version(
            document_id=doc_id,
            filename="v2.md",
            stream=BytesIO((MANUAL + "\n\n## 4. Anexo\n\nTexto novo da segunda versao.").encode()),
        )
        await session.commit()
        v2 = versao2.id

    # Entre o upload e o processamento, a v1 continua corrente: o documento nao some
    # da busca enquanto a v2 e indexada.
    assert (await estado_versao(session_factory, v1))[1] is True
    assert (await estado_versao(session_factory, v2))[0] == DocumentStatus.PENDING.value

    assert await worker.run_once(version_ids={v2}) is True

    s1, c1, _ = await estado_versao(session_factory, v1)
    s2, c2, _ = await estado_versao(session_factory, v2)
    assert (s1, c1) == (DocumentStatus.SUPERSEDED.value, False)
    assert (s2, c2) == (DocumentStatus.READY.value, True)


# --- Falhas ------------------------------------------------------------------


@requires_db
async def test_pdf_sem_texto_falha_sem_retry(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    """Retentar um PDF escaneado e inutil: o arquivo nao ganha texto entre tentativas."""
    _, version_id = await upload(
        session_factory,
        storage,
        admin,
        conteudo=b"%PDF-1.4\n" + uuid.uuid4().hex.encode() + b"\ntrailer\n%%EOF\n",
        filename="escaneado.pdf",
    )
    worker = build_worker(settings, session_factory, storage)
    assert await worker.run_once(version_ids={version_id}) is True

    status, corrente, _ = await estado_versao(session_factory, version_id)
    assert status == DocumentStatus.FAILED.value
    assert corrente is False

    job_status, tentativas, erro = await estado_job(session_factory, version_id)
    assert job_status == "FAILED"
    assert tentativas == 1  # nao voltou para a fila
    assert erro

    async with session_factory() as session:
        codigo = await session.scalar(
            text("SELECT error_code FROM document_versions WHERE id = :id"), {"id": version_id}
        )
    assert codigo in {"NO_TEXT_LAYER", "EXTRACTION_FAILED"}


@requires_db
async def test_falha_de_embedding_volta_para_a_fila_e_nao_grava_chunks(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    _, version_id = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="manual.md"
    )
    quebrado = FakeEmbeddingClient(fail=True)
    worker = build_worker(settings, session_factory, storage, quebrado)

    assert await worker.run_once(version_ids={version_id}) is True

    status, corrente, _ = await estado_versao(session_factory, version_id)
    job_status, tentativas, _ = await estado_job(session_factory, version_id)
    # Transitorio: volta para PENDING com a tentativa contada.
    assert (status, corrente) == (DocumentStatus.PENDING.value, False)
    assert (job_status, tentativas) == ("PENDING", 1)

    async with session_factory() as session:
        total = await session.scalar(
            text("SELECT count(*) FROM document_chunks WHERE document_version_id = :id"),
            {"id": version_id},
        )
    assert total == 0

    # Esgota as tentativas restantes.
    while await worker.run_once(version_ids={version_id}):
        pass
    status, _, _ = await estado_versao(session_factory, version_id)
    job_status, tentativas, _ = await estado_job(session_factory, version_id)
    assert status == DocumentStatus.FAILED.value
    assert (job_status, tentativas) == ("FAILED", 3)

    # Recuperacao: o cliente volta a funcionar e o admin pede reprocessamento.
    async with session_factory() as session:
        service = DocumentService(
            documents=DocumentRepository(session),
            versions=DocumentVersionRepository(session),
            jobs=ProcessingJobRepository(session),
            storage=storage,  # type: ignore[arg-type]
        )
        doc_id = await session.scalar(
            text("SELECT document_id FROM document_versions WHERE id = :id"), {"id": version_id}
        )
        await service.reprocess(doc_id)
        await session.commit()

    bom = build_worker(settings, session_factory, storage, FakeEmbeddingClient())
    assert await bom.run_once(version_ids={version_id}) is True
    status, corrente, chunk_count = await estado_versao(session_factory, version_id)
    assert (status, corrente) == (DocumentStatus.READY.value, True)
    assert chunk_count and chunk_count > 0


@requires_db
async def test_job_running_abandonado_volta_para_a_fila(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    _, version_id = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="manual.md"
    )
    # Simula um processo que morreu no meio: RUNNING ha uma hora.
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE processing_jobs SET status = 'RUNNING', "
                "started_at = now() - interval '1 hour' WHERE document_version_id = :id"
            ),
            {"id": version_id},
        )
        await session.commit()

    worker = build_worker(settings, session_factory, storage)
    await worker.recover_stale()

    job_status, _, _ = await estado_job(session_factory, version_id)
    assert job_status == "PENDING"
