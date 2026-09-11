"""Agregacoes do Intelligence contra PostgreSQL real.

Gera consultas de verdade pelo RagService (com Gemini falso) e confere que os
numeros batem com o que foi gerado — sucesso, recusa, feedback, citacoes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Environment, Settings
from app.modules.feedback.models import FeedbackRating, FeedbackReason
from app.modules.feedback.repository import FeedbackRepository
from app.modules.intelligence.repository import IntelligenceRepository
from app.modules.intelligence.service import AMOSTRA_MINIMA, IntelligenceService
from app.modules.queries.repository import QueryRepository
from app.modules.rag.service import RagService
from app.modules.search.repository import SearchRepository
from app.modules.search.service import SearchService
from app.modules.users.models import User
from tests.fakes import FakeEmbeddingClient, FakeGenerationClient, FakeStorage
from tests.integration.conftest import DATABASE_URL, requires_db
from tests.integration.test_ingestion_worker import MANUAL, build_worker, upload

pytestmark = pytest.mark.integration


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


@requires_db
async def test_visao_geral_reflete_as_consultas_reais(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    admin: User,
) -> None:
    _, version_id = await upload(
        session_factory, storage, admin, conteudo=MANUAL.encode(), filename="m.md"
    )
    await build_worker(settings, session_factory, storage).run_once(version_ids={version_id})

    geracao = FakeGenerationClient({"answer": "A cada 24 meses [C1].", "citations": ["C1"]})
    ids: list[uuid.UUID] = []
    async with session_factory() as session:
        rag = RagService(
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
        for _ in range(2):
            r = await rag.answer("atualizacao cadastral vinte e quatro meses", user_id=admin.id)
            ids.append(r.query_id)
        # Duas lacunas semelhantes e uma diferente.
        await rag.answer("taxa de juros do financiamento imobiliario", user_id=admin.id)
        await rag.answer("qual a taxa de juros do financiamento imobiliario", user_id=admin.id)
        await rag.answer("horario da agencia da avenida paulista", user_id=admin.id)
        await FeedbackRepository(session).upsert(
            query_id=ids[0],
            user_id=admin.id,
            rating=FeedbackRating.NEGATIVE,
            reason=FeedbackReason.INCOMPLETE,
            comment=None,
        )
        await session.commit()

    async with session_factory() as session:
        visao = await IntelligenceService(IntelligenceRepository(session)).visao_geral(dias=1)

    # O banco e compartilhado: afirmamos "pelo menos", nunca igualdade sobre totais.
    assert visao.totais.consultas >= 5
    assert visao.totais.sucesso >= 2
    assert visao.totais.sem_evidencia >= 3
    if visao.totais.consultas < AMOSTRA_MINIMA:
        assert visao.taxa_sucesso is None and not visao.amostra_suficiente
    else:
        assert visao.taxa_sucesso is not None
    assert visao.latencia.p50_ms is not None and visao.latencia.p95_ms is not None
    assert visao.latencia.p95_ms >= visao.latencia.p50_ms
    assert visao.confianca_media is not None and 0 < visao.confianca_media <= 1

    assert visao.feedback.negativos >= 1
    assert ("INCOMPLETE", 1) in [(m, c) for m, c in visao.feedback.motivos] or any(
        m == "INCOMPLETE" for m, _ in visao.feedback.motivos
    )

    citados = {d.title: d for d in visao.documentos_mais_citados}
    assert "Manual de Cadastro" in citados
    assert citados["Manual de Cadastro"].citacoes >= 2
    assert citados["Manual de Cadastro"].consultas >= 2
    assert any("Atualizacao" in (s.section_path or "") for s in visao.secoes_mais_citadas)

    representantes = {g.representante: g for g in visao.lacunas}
    juros = next(g for r, g in representantes.items() if "juros" in r)
    assert juros.ocorrencias >= 2
    assert any("paulista" in r for r in representantes)

    assert len(visao.serie_diaria) >= 1
    assert sum(d.consultas for d in visao.serie_diaria) == visao.totais.consultas
    assert visao.documentos_ativos >= 1 and visao.chunks_indexados >= 1
