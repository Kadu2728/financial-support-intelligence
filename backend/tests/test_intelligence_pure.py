"""Intelligence sem banco: guarda de amostra, preenchimento de dias, agrupamento."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from app.modules.intelligence.repository import DiaSerie, Lacuna
from app.modules.intelligence.service import _preencher_dias, _taxa, agrupar_lacunas
from tests.fakes import embed_fake


def test_taxa_e_nula_sem_amostra_suficiente() -> None:
    assert _taxa(3, 3, permitido=False) is None
    assert _taxa(0, 0, permitido=True) is None
    assert _taxa(15, 20, permitido=True) == 0.75


def test_dias_sem_consulta_entram_com_zero() -> None:
    inicio = date(2026, 9, 1)
    serie = [DiaSerie(dia=date(2026, 9, 2), consultas=4, sem_evidencia=1)]
    preenchida = _preencher_dias(serie, inicio, date(2026, 9, 4))

    assert [d.dia.day for d in preenchida] == [1, 2, 3, 4]
    assert [d.consultas for d in preenchida] == [0, 4, 0, 0]


def lacuna(pergunta: str, *, minutos_atras: int, embedding: list[float] | None = None) -> Lacuna:
    return Lacuna(
        query_id=uuid.uuid4(),
        question=pergunta,
        created_at=datetime.now(UTC) - timedelta(minutes=minutos_atras),
        top_score=0.3,
        embedding=embed_fake(pergunta) if embedding is None else embedding,
    )


def test_perguntas_semelhantes_viram_um_grupo_com_contagem() -> None:
    lacunas = [
        lacuna("qual a taxa de juros do financiamento imobiliario", minutos_atras=1),
        lacuna("horario da agencia da avenida paulista", minutos_atras=2),
        lacuna("qual a taxa de juros do financiamento imobiliario hoje", minutos_atras=3),
        lacuna("taxa de juros do financiamento imobiliario", minutos_atras=4),
    ]
    grupos = agrupar_lacunas(lacunas, limiar=0.6)

    assert [g.ocorrencias for g in grupos] == [3, 1]
    # A representante e a mais recente do grupo.
    assert grupos[0].representante == "qual a taxa de juros do financiamento imobiliario"
    assert len(grupos[0].exemplos) == 2
    assert len(grupos[0].query_ids) == 3
    assert grupos[1].representante == "horario da agencia da avenida paulista"


def test_lacuna_sem_embedding_nao_e_descartada() -> None:
    lacunas = [
        lacuna("pergunta a", minutos_atras=1, embedding=[]),
        lacuna("pergunta a", minutos_atras=2, embedding=[]),
    ]
    for item in lacunas:
        object.__setattr__(item, "embedding", None)
    grupos = agrupar_lacunas(lacunas)
    assert [g.ocorrencias for g in grupos] == [1, 1]


def test_limiar_alto_nao_agrupa_perguntas_diferentes() -> None:
    lacunas = [
        lacuna("segunda via do boleto do consorcio", minutos_atras=1),
        lacuna("quantos funcionarios o banco tem", minutos_atras=2),
    ]
    assert len(agrupar_lacunas(lacunas, limiar=0.8)) == 2


def test_pergunta_identica_repetida_conta_mas_nao_vira_exemplo() -> None:
    """Visto na tela: "2x pergunta X — Tambem: pergunta X". A repeticao ja esta na
    contagem; como exemplo, e ruido."""
    lacunas = [
        lacuna("Qual o procedimento para abertura de conta de pessoa juridica?", minutos_atras=1),
        lacuna("qual o procedimento para abertura de conta de pessoa juridica", minutos_atras=2),
        lacuna(
            "Como abrir conta PJ?",
            minutos_atras=3,
            embedding=embed_fake("abertura conta juridica procedimento"),
        ),
    ]
    grupos = agrupar_lacunas(lacunas, limiar=0.3)

    assert grupos[0].ocorrencias == 3
    assert grupos[0].exemplos == ["Como abrir conta PJ?"]
