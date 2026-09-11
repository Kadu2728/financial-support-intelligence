"""Busca hibrida com Reciprocal Rank Fusion (ADR-0002).

    pergunta ─┬─ semantica (cosine, top-30) ─┐
              └─ lexical  (ts_rank, top-30) ─┴─ RRF(k=60) ─ dedup por secao ─ top-8

RRF funde POSICOES, nao scores. Cosine varia em [0,1] e ts_rank_cd e ilimitado; somar
os dois com pesos exigiria normalizar escalas que nao sao comparaveis, e o peso
"certo" mudaria com o acervo. Com posicoes, um chunk que e 1o numa perna e ausente na
outra ainda entra bem ranqueado — e o que salva a consulta literal ("COD-2041"), em
que a perna semantica dilui justamente o token que importa.

A funcao `fundir` e pura e sem I/O: e onde a logica de ranking vive, e e testada
sem banco.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import structlog

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.integrations.gemini.client import EmbeddingClient, TaskType
from app.modules.search.repository import ChunkRecuperado, SearchRepository

logger = structlog.get_logger(__name__)


class SearchMode(StrEnum):
    SEMANTIC = "semantic"
    LEXICAL = "lexical"
    HYBRID = "hybrid"


class QuestionTooLongError(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_ERROR
    message = "A pergunta e longa demais."


@dataclass(frozen=True, slots=True)
class Hit:
    chunk: ChunkRecuperado
    score: float
    semantic_rank: int | None
    lexical_rank: int | None

    @property
    def similarity(self) -> float | None:
        return self.chunk.similarity


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: list[Hit]
    mode: SearchMode
    retrieval_ms: int
    embedding: list[float] | None
    candidatos_semanticos: int = 0
    candidatos_lexicais: int = 0
    # Contagem do que foi fundido antes do dedup e do corte — para diagnostico.
    fundidos: int = 0

    @property
    def top_similarity(self) -> float | None:
        """Maior similaridade cosine entre os finalistas — entrada do gate."""
        valores = [h.similarity for h in self.hits if h.similarity is not None]
        return max(valores) if valores else None


@dataclass(frozen=True, slots=True)
class Fundido:
    chunk_id: uuid.UUID
    score: float
    semantic_rank: int | None
    lexical_rank: int | None


def fundir(
    semanticos: Sequence[uuid.UUID],
    lexicais: Sequence[uuid.UUID],
    *,
    k: int = 60,
) -> list[Fundido]:
    """Reciprocal Rank Fusion: score(d) = Σ 1 / (k + rank_i(d)), rank a partir de 1.

    `k=60` e o valor canonico do artigo original: grande o bastante para que a
    diferenca entre 1o e 2o lugar nao domine, pequeno o bastante para que a posicao
    ainda importe.
    """
    scores: dict[uuid.UUID, float] = {}
    pos_sem: dict[uuid.UUID, int] = {}
    pos_lex: dict[uuid.UUID, int] = {}

    for posicao, chunk_id in enumerate(semanticos, start=1):
        pos_sem.setdefault(chunk_id, posicao)
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + posicao)

    for posicao, chunk_id in enumerate(lexicais, start=1):
        pos_lex.setdefault(chunk_id, posicao)
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + posicao)

    ordenados = sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))
    return [
        Fundido(
            chunk_id=chunk_id,
            score=score,
            semantic_rank=pos_sem.get(chunk_id),
            lexical_rank=pos_lex.get(chunk_id),
        )
        for chunk_id, score in ordenados
    ]


def deduplicar_por_secao(hits: Sequence[Hit]) -> list[Hit]:
    """Mantem o melhor chunk de cada secao.

    Quatro chunks da mesma secao ocupariam metade do contexto dizendo a mesma coisa.
    Chunks sem secao (documento sem estrutura) nao sao deduplicados entre si: nao ha
    como saber se falam do mesmo assunto.
    """
    vistos: set[tuple[uuid.UUID, str]] = set()
    resultado: list[Hit] = []
    for hit in hits:
        caminho = hit.chunk.section_path
        if caminho is None:
            resultado.append(hit)
            continue
        chave = (hit.chunk.version_id, caminho)
        if chave in vistos:
            continue
        vistos.add(chave)
        resultado.append(hit)
    return resultado


class SearchService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: SearchRepository,
        embeddings: EmbeddingClient | None,
    ) -> None:
        self._settings = settings
        self._repo = repository
        self._embeddings = embeddings

    async def search(
        self,
        pergunta: str,
        *,
        mode: SearchMode = SearchMode.HYBRID,
        top_k: int | None = None,
        embedding: Sequence[float] | None = None,
    ) -> SearchResult:
        """Executa a busca. `embedding` ja calculado evita uma segunda chamada ao
        Gemini quando o RAG precisa guardar o vetor da pergunta."""
        pergunta = pergunta.strip()
        if not pergunta:
            return SearchResult(hits=[], mode=mode, retrieval_ms=0, embedding=None)
        if len(pergunta) > self._settings.rag_max_question_chars:
            raise QuestionTooLongError(details={"max_chars": self._settings.rag_max_question_chars})

        limite_final = top_k or self._settings.search_top_k
        por_perna = self._settings.search_candidates_per_leg
        inicio = time.perf_counter()

        vetor: list[float] | None = list(embedding) if embedding is not None else None
        semanticos: list[tuple[uuid.UUID, float]] = []
        lexicais: list[tuple[uuid.UUID, float]] = []

        if mode is not SearchMode.LEXICAL:
            if vetor is None:
                vetor = await self._embed(pergunta)
            semanticos = await self._repo.semantic(vetor, limit=por_perna)

        if mode is not SearchMode.SEMANTIC:
            lexicais = await self._repo.lexical(pergunta, limit=por_perna)

        fundidos = fundir(
            [c for c, _ in semanticos],
            [c for c, _ in lexicais],
            k=self._settings.search_rrf_k,
        )

        # Busca mais finalistas que o necessario: o dedup por secao pode descartar
        # varios, e cortar antes dele deixaria buracos no top-K.
        candidatos = fundidos[: limite_final * 3]
        registros = await self._repo.fetch([f.chunk_id for f in candidatos], embedding=vetor)

        hits = [
            Hit(
                chunk=registros[f.chunk_id],
                score=f.score,
                semantic_rank=f.semantic_rank,
                lexical_rank=f.lexical_rank,
            )
            for f in candidatos
            if f.chunk_id in registros
        ]
        finais = deduplicar_por_secao(hits)[:limite_final]

        resultado = SearchResult(
            hits=finais,
            mode=mode,
            retrieval_ms=int((time.perf_counter() - inicio) * 1000),
            embedding=vetor,
            candidatos_semanticos=len(semanticos),
            candidatos_lexicais=len(lexicais),
            fundidos=len(fundidos),
        )
        logger.info(
            "search_executed",
            mode=mode.value,
            hits=len(finais),
            semantic=len(semanticos),
            lexical=len(lexicais),
            top_similarity=resultado.top_similarity,
            retrieval_ms=resultado.retrieval_ms,
        )
        return resultado

    async def embed_question(self, pergunta: str) -> list[float]:
        return await self._embed(pergunta)

    async def _embed(self, pergunta: str) -> list[float]:
        if self._embeddings is None:
            from app.integrations.gemini.client import GeminiNotConfiguredError

            raise GeminiNotConfiguredError
        [vetor] = await self._embeddings.embed([pergunta], task_type=TaskType.RETRIEVAL_QUERY)
        return vetor
