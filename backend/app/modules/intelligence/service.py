"""Support Intelligence: o que o acervo responde, o que nao responde, e como.

Duas regras que definem o modulo:

1. **Metricas computadas, nunca estimadas.** Cada numero vem de uma agregacao do
   repositorio; este service so organiza e deriva taxas.
2. **Guarda de amostra minima.** Taxas sobre menos de `AMOSTRA_MINIMA` consultas
   sao `None`. "100% de sucesso" sobre 3 perguntas nao e informacao, e um gestor
   tomaria decisao em cima disso.

O agrupamento de lacunas usa os embeddings ja gravados em `queries.embedding`:
perguntas que o acervo nao respondeu e que sao semelhantes entre si viram um unico
item com contagem — "12 pessoas perguntaram sobre X" e acionavel; 12 linhas soltas
nao sao.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.modules.intelligence.repository import (
    DiaSerie,
    DocumentoCitado,
    IntelligenceRepository,
    Lacuna,
    Latencia,
    ResumoFeedback,
    SecaoCitada,
    Totais,
)

# Abaixo disto, taxas nao sao exibidas. Vinte e o menor n em que uma proporcao
# tem intervalo de confianca com alguma utilidade (±20 p.p. a 95%).
AMOSTRA_MINIMA = 20

# Similaridade cosine acima da qual duas perguntas sem resposta sao "a mesma".
# Alto de proposito: agrupar perguntas diferentes esconderia lacunas distintas.
LIMIAR_AGRUPAMENTO = 0.80


@dataclass(frozen=True, slots=True)
class GrupoLacuna:
    representante: str
    ocorrencias: int
    exemplos: list[str]
    ultima_em: datetime
    query_ids: list[str]


@dataclass(frozen=True, slots=True)
class VisaoGeral:
    dias: int
    desde: datetime
    ate: datetime
    amostra_minima: int
    amostra_suficiente: bool
    totais: Totais
    taxa_sucesso: float | None
    taxa_sem_evidencia: float | None
    taxa_falha: float | None
    latencia: Latencia
    confianca_media: float | None
    feedback: ResumoFeedback
    taxa_feedback_positivo: float | None
    serie_diaria: list[DiaSerie]
    documentos_mais_citados: list[DocumentoCitado]
    secoes_mais_citadas: list[SecaoCitada]
    lacunas: list[GrupoLacuna]
    documentos_ativos: int
    chunks_indexados: int


class IntelligenceService:
    def __init__(self, repository: IntelligenceRepository) -> None:
        self._repo = repository

    async def visao_geral(self, *, dias: int) -> VisaoGeral:
        ate = datetime.now(UTC)
        desde = ate - timedelta(days=dias)

        totais = await self._repo.totais(desde)
        latencia = await self._repo.latencia(desde)
        confianca = await self._repo.confianca_media(desde)
        feedback = await self._repo.feedback(desde)
        serie = await self._repo.serie_diaria(desde)
        documentos = await self._repo.documentos_mais_citados(desde, limite=10)
        secoes = await self._repo.secoes_mais_citadas(desde, limite=10)
        lacunas = await self._repo.lacunas(desde, limite=200)
        docs_ativos, chunks = await self._repo.acervo()

        suficiente = totais.consultas >= AMOSTRA_MINIMA
        n = totais.consultas

        return VisaoGeral(
            dias=dias,
            desde=desde,
            ate=ate,
            amostra_minima=AMOSTRA_MINIMA,
            amostra_suficiente=suficiente,
            totais=totais,
            taxa_sucesso=_taxa(totais.sucesso, n, suficiente),
            taxa_sem_evidencia=_taxa(totais.sem_evidencia, n, suficiente),
            taxa_falha=_taxa(totais.falhas, n, suficiente),
            latencia=latencia,
            confianca_media=confianca,
            feedback=feedback,
            taxa_feedback_positivo=_taxa(
                feedback.positivos, feedback.total, feedback.total >= AMOSTRA_MINIMA
            ),
            serie_diaria=_preencher_dias(serie, desde.date(), ate.date()),
            documentos_mais_citados=documentos,
            secoes_mais_citadas=secoes,
            lacunas=agrupar_lacunas(lacunas),
            documentos_ativos=docs_ativos,
            chunks_indexados=chunks,
        )


def _taxa(parte: int, total: int, permitido: bool) -> float | None:
    if not permitido or total == 0:
        return None
    return round(parte / total, 3)


def _preencher_dias(serie: Sequence[DiaSerie], inicio: date, fim: date) -> list[DiaSerie]:
    """Dias sem consulta entram com zero: um grafico com buracos engana."""
    por_dia = {item.dia: item for item in serie}
    saida: list[DiaSerie] = []
    atual = inicio
    while atual <= fim:
        saida.append(por_dia.get(atual, DiaSerie(dia=atual, consultas=0, sem_evidencia=0)))
        atual += timedelta(days=1)
    return saida


def agrupar_lacunas(
    lacunas: Sequence[Lacuna], *, limiar: float = LIMIAR_AGRUPAMENTO
) -> list[GrupoLacuna]:
    """Agrupamento guloso por similaridade cosine com o representante do grupo.

    Guloso e nao k-means porque o numero de grupos nao e conhecido e o conjunto e
    pequeno (ate 200). A lacuna mais recente de cada grupo e a representante: e
    a formulacao que o gestor vai reconhecer.

    Lacunas sem embedding (consulta que falhou antes de embeddar) viram grupos
    proprios — nunca sao descartadas.
    """
    grupos: list[tuple[Lacuna, list[Lacuna]]] = []

    for lacuna in lacunas:  # ja vem mais recente primeiro
        alvo: list[Lacuna] | None = None
        if lacuna.embedding is not None:
            for representante, membros in grupos:
                if representante.embedding is None:
                    continue
                if _cosine(representante.embedding, lacuna.embedding) >= limiar:
                    alvo = membros
                    break
        if alvo is None:
            grupos.append((lacuna, [lacuna]))
        else:
            alvo.append(lacuna)

    saida = [
        GrupoLacuna(
            representante=representante.question,
            ocorrencias=len(membros),
            # So formulacoes DIFERENTES da representante: a mesma pergunta repetida
            # ja esta contada em `ocorrencias`, e repeti-la como "tambem" e ruido.
            exemplos=_formulacoes_distintas(representante.question, membros)[:3],
            ultima_em=representante.created_at,
            query_ids=[str(m.query_id) for m in membros],
        )
        for representante, membros in grupos
    ]
    saida.sort(key=lambda g: (-g.ocorrencias, -g.ultima_em.timestamp()))
    return saida


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    # Os embeddings sao L2-normalizados na entrada, entao o produto escalar ja e o
    # cosine; a divisao protege contra um vetor que nao passou pelo cliente.
    produto = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return produto / (na * nb) if na and nb else 0.0


def _formulacoes_distintas(representante: str, membros: list[Lacuna]) -> list[str]:
    vistas = {_normalizar_pergunta(representante)}
    saida: list[str] = []
    for membro in membros:
        chave = _normalizar_pergunta(membro.question)
        if chave in vistas:
            continue
        vistas.add(chave)
        saida.append(membro.question)
    return saida


def _normalizar_pergunta(texto: str) -> str:
    return " ".join(texto.lower().split()).rstrip("?!. ")
