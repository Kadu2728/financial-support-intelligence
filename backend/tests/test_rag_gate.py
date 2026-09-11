"""Gate de evidencia: decisao pura sobre similaridades."""

from __future__ import annotations

import uuid

import pytest

from app.core.config import Settings
from app.modules.rag.gate import avaliar_gate
from app.modules.search.repository import ChunkRecuperado
from app.modules.search.service import Hit


@pytest.fixture
def settings() -> Settings:
    return Settings(
        jwt_secret_key="segredo-de-teste-com-tamanho-suficiente",
        rag_min_top_score=0.55,
        rag_min_support_score=0.45,
        rag_min_support_count=2,
    )


def hit(similarity: float | None) -> Hit:
    chunk = ChunkRecuperado(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Doc",
        version_id=uuid.uuid4(),
        chunk_index=0,
        section_path=None,
        section_label=None,
        page_number=None,
        content="x",
        content_tokens=1,
        char_start=0,
        char_end=1,
        similarity=similarity,
    )
    return Hit(chunk=chunk, score=0.0, semantic_rank=None, lexical_rank=None)


def test_aprova_com_topo_e_suporte(settings: Settings) -> None:
    decisao = avaliar_gate([hit(0.70), hit(0.50), hit(0.20)], settings)
    assert decisao.aprovado
    assert decisao.top_similarity == 0.70
    assert decisao.suporte == 2


def test_recusa_sem_candidatos(settings: Settings) -> None:
    decisao = avaliar_gate([], settings)
    assert not decisao.aprovado
    assert decisao.motivo == "sem_candidatos"


def test_recusa_topo_fraco_mesmo_com_muitos_medianos(settings: Settings) -> None:
    decisao = avaliar_gate([hit(0.54), hit(0.50), hit(0.48)], settings)
    assert not decisao.aprovado
    assert decisao.motivo == "topo_abaixo_do_limiar"


def test_recusa_um_unico_chunk_bom_sem_suporte(settings: Settings) -> None:
    """Um chunk parecido pode ser coincidencia de vocabulario."""
    decisao = avaliar_gate([hit(0.80), hit(0.30), hit(0.10)], settings)
    assert not decisao.aprovado
    assert decisao.motivo == "suporte_insuficiente"
    assert decisao.suporte == 1


def test_o_topo_conta_como_suporte(settings: Settings) -> None:
    decisao = avaliar_gate([hit(0.60), hit(0.45)], settings)
    assert decisao.aprovado
    assert decisao.suporte == 2


def test_ignora_hits_sem_similaridade(settings: Settings) -> None:
    decisao = avaliar_gate([hit(None), hit(None)], settings)
    assert not decisao.aprovado
    assert decisao.motivo == "sem_candidatos"


def test_limiares_vem_da_configuracao() -> None:
    frouxo = Settings(
        jwt_secret_key="segredo-de-teste-com-tamanho-suficiente",
        rag_min_top_score=0.30,
        rag_min_support_score=0.20,
        rag_min_support_count=1,
    )
    assert avaliar_gate([hit(0.35)], frouxo).aprovado
