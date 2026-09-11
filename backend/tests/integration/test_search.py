"""Busca hibrida contra PostgreSQL real.

O que so o banco prova: o operador `<=>` do pgvector, o `@@` sobre a coluna gerada
`tsv` com a configuracao 'portuguese' (stemming), e o filtro de `is_current` e de
soft delete nas duas pernas.

Os embeddings sao os do fake (hash de palavras), entao a "semantica" aqui e
sobreposicao lexical disfarcada. O que se valida e a MECANICA da busca, nao a
qualidade do modelo — essa so a avaliacao com chave real mede (scripts/avaliar_busca.py).
"""

from __future__ import annotations

from io import BytesIO

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.documents.repository import DocumentRepository, DocumentVersionRepository
from app.modules.documents.service import DocumentService
from app.modules.ingestion.repository import ProcessingJobRepository
from app.modules.search.repository import SearchRepository
from app.modules.search.service import SearchMode, SearchService
from app.modules.users.models import User
from tests.fakes import FakeEmbeddingClient, FakeStorage
from tests.integration.conftest import requires_db
from tests.integration.test_ingestion_worker import MANUAL, build_worker, upload

pytestmark = pytest.mark.integration


def build_search(settings: Settings, session: AsyncSession) -> SearchService:
    return SearchService(
        settings=settings,
        repository=SearchRepository(session),
        embeddings=FakeEmbeddingClient(),
    )


@requires_db
async def test_lexical_encontra_pela_raiz_da_palavra(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    _, version_id = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="m.md"
    )
    await build_worker(settings, session_factory, storage).run_once(version_ids={version_id})

    async with session_factory() as session:
        # "encerramentos" (plural) casa "encerramento" pelo stemmer portugues.
        resultado = await build_search(settings, session).search(
            "prazo dos encerramentos com saldo zerado", mode=SearchMode.LEXICAL
        )

    assert resultado.hits
    assert resultado.hits[0].chunk.version_id == version_id
    assert "Encerramento" in (resultado.hits[0].chunk.section_path or "")
    assert resultado.hits[0].lexical_rank == 1
    assert resultado.hits[0].semantic_rank is None
    # Sem perna semantica nao ha similaridade para o gate.
    assert resultado.top_similarity is None


@requires_db
async def test_semantica_e_hibrida_trazem_similaridade_para_todos(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    _, version_id = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="m.md"
    )
    await build_worker(settings, session_factory, storage).run_once(version_ids={version_id})

    async with session_factory() as session:
        servico = build_search(settings, session)
        semantica = await servico.search(
            "atualizacao cadastral a cada vinte e quatro meses", mode=SearchMode.SEMANTIC
        )
        hibrida = await servico.search(
            "atualizacao cadastral a cada vinte e quatro meses", mode=SearchMode.HYBRID
        )

    assert semantica.hits and hibrida.hits
    assert "Atualizacao" in (semantica.hits[0].chunk.section_path or "")
    assert semantica.top_similarity is not None and semantica.top_similarity > 0
    # Na hibrida, ate um chunk trazido so pela perna lexical recebe similaridade:
    # o gate precisa de um numero comparavel por finalista.
    assert all(h.similarity is not None for h in hibrida.hits)
    assert hibrida.embedding is not None and len(hibrida.embedding) == 768
    # O topo da hibrida esta nas duas pernas.
    topo = hibrida.hits[0]
    assert topo.semantic_rank is not None and topo.lexical_rank is not None


@requires_db
async def test_so_a_versao_corrente_e_pesquisavel(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    doc_id, v1 = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="v1.md"
    )
    worker = build_worker(settings, session_factory, storage)
    await worker.run_once(version_ids={v1})

    async with session_factory() as session:
        service = DocumentService(
            documents=DocumentRepository(session),
            versions=DocumentVersionRepository(session),
            jobs=ProcessingJobRepository(session),
            storage=storage,  # type: ignore[arg-type]
        )
        v2 = (
            await service.add_version(
                document_id=doc_id,
                filename="v2.md",
                stream=BytesIO(
                    MANUAL.replace("vinte e quatro meses", "trinta e seis meses").encode()
                ),
            )
        ).id
        await session.commit()
    await worker.run_once(version_ids={v2})

    async with session_factory() as session:
        resultado = await build_search(settings, session).search(
            "atualizacao cadastral trinta e seis meses", mode=SearchMode.HYBRID
        )

    versoes = {h.chunk.version_id for h in resultado.hits}
    assert v2 in versoes
    assert v1 not in versoes


@requires_db
async def test_documento_excluido_some_da_busca(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    doc_id, version_id = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="m.md"
    )
    await build_worker(settings, session_factory, storage).run_once(version_ids={version_id})

    async with session_factory() as session:
        antes = await build_search(settings, session).search(
            "encerramento saldo zerado", mode=SearchMode.LEXICAL
        )
        assert any(h.chunk.version_id == version_id for h in antes.hits)

        await DocumentService(
            documents=DocumentRepository(session),
            versions=DocumentVersionRepository(session),
            jobs=ProcessingJobRepository(session),
            storage=storage,  # type: ignore[arg-type]
        ).delete_document(doc_id)
        await session.commit()

    async with session_factory() as session:
        depois = await build_search(settings, session).search(
            "encerramento saldo zerado", mode=SearchMode.LEXICAL
        )
    assert all(h.chunk.version_id != version_id for h in depois.hits)


@requires_db
async def test_pergunta_sem_nenhum_termo_no_acervo_devolve_vazio_na_lexical(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        resultado = await build_search(settings, session).search(
            "xyzzy plugh qwerty", mode=SearchMode.LEXICAL
        )
    assert resultado.hits == []
