"""Logica de ranking, sem banco: RRF e dedup por secao."""

from __future__ import annotations

import uuid

import pytest

from app.modules.search.repository import ChunkRecuperado
from app.modules.search.service import Hit, deduplicar_por_secao, fundir

A, B, C, D = (uuid.uuid4() for _ in range(4))


def test_rrf_soma_as_duas_pernas() -> None:
    fundidos = fundir([A, B, C], [B, D], k=60)

    por_id = {f.chunk_id: f for f in fundidos}
    # B: 2o na semantica e 1o na lexical.
    assert por_id[B].score == pytest.approx(1 / 62 + 1 / 61)
    assert por_id[B].semantic_rank == 2
    assert por_id[B].lexical_rank == 1
    # A: so na semantica.
    assert por_id[A].score == pytest.approx(1 / 61)
    assert por_id[A].lexical_rank is None
    assert fundidos[0].chunk_id == B


def test_rrf_presenca_nas_duas_pernas_vence_primeiro_lugar_isolado() -> None:
    """E a propriedade que salva a consulta literal: um chunk mediano nas duas pernas
    supera um que e 1o numa e ausente na outra."""
    fundidos = fundir([A, B, C], [C, B, D], k=60)
    # B: posicoes 2 e 2. A: posicao 1 e ausente. C: 3 e 1.
    ordem = [f.chunk_id for f in fundidos]
    assert ordem.index(B) < ordem.index(A)
    assert ordem.index(C) < ordem.index(A)


def test_rrf_k_menor_acentua_o_topo() -> None:
    com_k_grande = fundir([A, B], [], k=1000)
    com_k_pequeno = fundir([A, B], [], k=1)
    razao_grande = com_k_grande[0].score / com_k_grande[1].score
    razao_pequena = com_k_pequeno[0].score / com_k_pequeno[1].score
    assert razao_pequena > razao_grande


def test_rrf_e_deterministico_em_empate() -> None:
    primeiro = [f.chunk_id for f in fundir([A, B], [B, A])]
    segundo = [f.chunk_id for f in fundir([A, B], [B, A])]
    assert primeiro == segundo


def test_rrf_listas_vazias() -> None:
    assert fundir([], []) == []


def chunk(section_path: str | None, version: uuid.UUID) -> ChunkRecuperado:
    return ChunkRecuperado(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Doc",
        version_id=version,
        chunk_index=0,
        section_path=section_path,
        section_label=None,
        page_number=None,
        content="x",
        content_tokens=1,
        char_start=0,
        char_end=1,
        similarity=None,
    )


def hit(section_path: str | None, version: uuid.UUID, score: float) -> Hit:
    return Hit(
        chunk=chunk(section_path, version), score=score, semantic_rank=None, lexical_rank=None
    )


def test_dedup_mantem_o_primeiro_de_cada_secao() -> None:
    v = uuid.uuid4()
    hits = [
        hit("1 > 1.2", v, 0.9),
        hit("1 > 1.2", v, 0.8),  # mesma secao: descartado
        hit("2", v, 0.7),
        hit("1 > 1.2", v, 0.6),  # descartado
    ]
    resultado = deduplicar_por_secao(hits)
    assert [h.score for h in resultado] == [0.9, 0.7]


def test_dedup_distingue_versoes_de_documentos_diferentes() -> None:
    """A mesma secao "3.1" em dois manuais diferentes nao e duplicata."""
    hits = [hit("3.1", uuid.uuid4(), 0.9), hit("3.1", uuid.uuid4(), 0.8)]
    assert len(deduplicar_por_secao(hits)) == 2


def test_dedup_nao_agrupa_chunks_sem_secao() -> None:
    v = uuid.uuid4()
    hits = [hit(None, v, 0.9), hit(None, v, 0.8)]
    assert len(deduplicar_por_secao(hits)) == 2
