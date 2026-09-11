"""RAG de ponta a ponta contra PostgreSQL real, com Gemini falso.

O que so o banco prova: a persistencia de Query + Answer + Citation na mesma
transacao, a FK das citacoes para chunks reais, o commit explicito da consulta FAILED
apesar do rollback, e a leitura de volta pelo historico com as citacoes resolvidas.

Os limiares do gate sao rebaixados de proposito: os embeddings do fake sao hashing
de palavras e produzem similaridades baixas. O que se testa e a MECANICA — a
calibracao dos limiares reais e trabalho de scripts/avaliar_busca.py.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Environment, Settings
from app.integrations.gemini.client import GeminiError
from app.modules.queries.models import QueryStatus
from app.modules.queries.repository import QueryRepository
from app.modules.queries.schemas import QueryOut
from app.modules.rag.service import RECUSA_CANONICA, RagService
from app.modules.search.repository import SearchRepository
from app.modules.search.service import SearchService
from app.modules.users.models import User
from tests.fakes import FakeEmbeddingClient, FakeGenerationClient, FakeStorage
from tests.integration.conftest import DATABASE_URL, requires_db
from tests.integration.test_ingestion_worker import MANUAL, build_worker, upload

pytestmark = pytest.mark.integration

PERGUNTA = "atualizacao cadastral a cada vinte e quatro meses exige comprovante?"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        app_env=Environment.TEST,
        jwt_secret_key="segredo-de-teste-com-tamanho-suficiente",
        worker_enabled=False,
        rag_min_top_score=0.15,
        rag_min_support_score=0.05,
        rag_min_support_count=1,
    )


@pytest.fixture
async def acervo(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> uuid.UUID:
    _, version_id = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="manual.md"
    )
    assert await build_worker(settings, session_factory, storage).run_once(version_ids={version_id})
    return version_id


def build_rag(
    settings: Settings, session: AsyncSession, geracao: FakeGenerationClient | None
) -> RagService:
    return RagService(
        settings=settings,
        search=SearchService(
            settings=settings,
            repository=SearchRepository(session),
            embeddings=FakeEmbeddingClient(),
        ),
        generation=geracao,  # type: ignore[arg-type]
        queries=QueryRepository(session),
        session=session,
    )


@requires_db
async def test_resposta_com_citacoes_e_persistida_e_relida(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    acervo: uuid.UUID,
    admin: User,
) -> None:
    geracao = FakeGenerationClient(
        {
            "answer": "A cada 24 meses [C1]. Renda acima de cinco mil exige comprovante [C1].",
            "citations": ["C1"],
            "insufficient_evidence": False,
            "confidence": 0.99,
        }
    )
    async with session_factory() as session:
        resposta = await build_rag(settings, session, geracao).answer(PERGUNTA, user_id=admin.id)
        await session.commit()

    assert resposta.status is QueryStatus.SUCCESS
    assert len(resposta.citations) == 1
    assert resposta.citations[0].hit.chunk.version_id == acervo
    assert resposta.confidence is not None and 0 < resposta.confidence <= 1
    # A confianca exibida NAO e a que o modelo reportou (0.99).
    assert resposta.confidence != 0.99
    # O prompt levou o contexto delimitado e a pergunta por ultimo.
    system, user = geracao.prompts[0]
    assert "C1, C2" in system
    assert user.rstrip().endswith(PERGUNTA)
    assert 'id="C1"' in user

    # Releitura pelo caminho do historico: mesma forma, citacoes resolvidas.
    async with session_factory() as session:
        repo = QueryRepository(session)
        query = await repo.get(resposta.query_id)
        assert query is not None and query.answer is not None
        citacoes = await repo.resolve_citations(query.answer.id)
        saida = QueryOut.from_query(query, citacoes, feedback_de=admin.id)

    assert saida.status is QueryStatus.SUCCESS
    assert saida.answer and "[C1]" in saida.answer
    assert [c.id for c in saida.citations] == ["C1"]
    assert saida.citations[0].document_title == "Manual de Cadastro"
    assert "Atualizacao" in (saida.citations[0].section_path or "")
    assert saida.citations[0].excerpt
    assert saida.model == "fake-generation"
    assert saida.retrieval_ms is not None and saida.generation_ms is not None
    assert query.embedding is not None and len(query.embedding) == 768


@requires_db
async def test_pergunta_fora_do_acervo_e_recusada_sem_chamar_o_modelo(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    acervo: uuid.UUID,
    admin: User,
) -> None:
    geracao = FakeGenerationClient({"answer": "NAO DEVERIA SER CHAMADO"})
    async with session_factory() as session:
        resposta = await build_rag(settings, session, geracao).answer(
            "qual a taxa de juros do financiamento imobiliario", user_id=admin.id
        )
        await session.commit()

    assert resposta.status is QueryStatus.INSUFFICIENT_EVIDENCE
    assert resposta.answer == RECUSA_CANONICA
    assert resposta.citations == []
    assert resposta.confidence is None
    assert geracao.prompts == []  # o gate barrou antes do modelo

    async with session_factory() as session:
        linha = (
            await session.execute(
                text(
                    "SELECT q.status, a.insufficient_evidence, a.raw_response->'gate'->>'reason' "
                    "FROM queries q JOIN answers a ON a.query_id = q.id WHERE q.id = :id"
                ),
                {"id": resposta.query_id},
            )
        ).one()
    assert linha[0] == "INSUFFICIENT_EVIDENCE"
    assert linha[1] is True
    assert linha[2] in {"topo_abaixo_do_limiar", "suporte_insuficiente", "sem_candidatos"}


@requires_db
async def test_citacao_inventada_e_descartada_e_registrada(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    acervo: uuid.UUID,
    admin: User,
) -> None:
    geracao = FakeGenerationClient(
        {"answer": "Prazo de 24 meses [C1] e taxa de 2% [C9].", "citations": ["C1", "C9"]}
    )
    async with session_factory() as session:
        resposta = await build_rag(settings, session, geracao).answer(PERGUNTA, user_id=admin.id)
        await session.commit()

    assert resposta.status is QueryStatus.SUCCESS
    assert resposta.citacoes_invalidas == ["C9"]
    assert resposta.answer == "Prazo de 24 meses [C1] e taxa de 2%."

    async with session_factory() as session:
        registro = await session.scalar(
            text(
                "SELECT a.raw_response->'invalid_citations' FROM answers a WHERE a.query_id = :id"
            ),
            {"id": resposta.query_id},
        )
    assert registro == ["C9"]


@requires_db
async def test_resposta_sem_citacao_valida_vira_recusa(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    acervo: uuid.UUID,
    admin: User,
) -> None:
    """Afirmacao sem fonte nao e melhor que nenhuma afirmacao — e pior."""
    geracao = FakeGenerationClient({"answer": "O prazo e de 10 dias.", "citations": ["C42"]})
    async with session_factory() as session:
        resposta = await build_rag(settings, session, geracao).answer(PERGUNTA, user_id=admin.id)
        await session.commit()

    assert resposta.status is QueryStatus.INSUFFICIENT_EVIDENCE
    assert resposta.answer == RECUSA_CANONICA
    assert resposta.confidence == 0.0


@requires_db
async def test_falha_de_geracao_fica_registrada_apesar_do_rollback(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    acervo: uuid.UUID,
    admin: User,
) -> None:
    """Reproduz o que `get_db` faz: a excecao sobe e a sessao sofre rollback.

    Sem o commit explicito no service, o registro FAILED seria descartado — e a
    taxa de erro do modelo no Intelligence seria sempre zero.
    """
    geracao = FakeGenerationClient(fail=True)
    async with session_factory() as session:
        with pytest.raises(GeminiError):
            await build_rag(settings, session, geracao).answer(PERGUNTA, user_id=admin.id)
        await session.rollback()

    async with session_factory() as session:
        linha = (
            await session.execute(
                text(
                    "SELECT status, error_code, generation_ms FROM queries "
                    "WHERE user_id = :u ORDER BY created_at DESC LIMIT 1"
                ),
                {"u": admin.id},
            )
        ).one()
    assert linha[0] == "FAILED"
    assert linha[1] == "UPSTREAM_UNAVAILABLE"
    assert linha[2] is not None
