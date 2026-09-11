"""Orquestrador do RAG (ADR-0008).

    pergunta -> busca hibrida -> gate -> contexto -> geracao JSON
             -> validacao de citacoes -> confianca calculada -> persistencia

Cinco camadas contra alucinacao, e nenhuma delas confia na anterior:

1. Gate de evidencia ANTES do modelo (`gate.py`).
2. Prompt que trata recusa como resposta legitima e contexto como dado (`prompt.py`).
3. JSON mode com schema fixo: a resposta e estruturada, nao texto livre a parsear.
4. Validacao de citacoes: identificador fora do contexto e descartado e registrado.
   O modelo NAO tem autoridade sobre as proprias fontes.
5. Confianca CALCULADA a partir do retrieval e das citacoes validas. O que o modelo
   diz sobre si mesmo vai para `raw_response` e nunca para a tela.

Toda consulta e persistida — sucesso, recusa e falha. As recusas sao o dado mais
valioso do produto: mostram o que o acervo nao cobre (modulo Intelligence).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.integrations.gemini.client import GeminiError, GenerationClient
from app.modules.queries.models import Answer, Citation, Query, QueryStatus
from app.modules.queries.repository import QueryRepository
from app.modules.rag.gate import DecisaoGate, avaliar_gate
from app.modules.rag.prompt import (
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    Contexto,
    montar_contexto,
    montar_mensagem,
)
from app.modules.search.service import Hit, SearchMode, SearchService

logger = structlog.get_logger(__name__)

RECUSA_CANONICA = (
    "Nao encontrei base suficiente nos documentos internos para responder a esta "
    "pergunta com seguranca. Recomendo confirmar com o gestor ou verificar se existe "
    "um documento sobre o tema que ainda nao foi adicionado ao acervo."
)

_MARCADOR_CITACAO = re.compile(r"\[(C\d+)\]")


class GenerationFailedError(AppError):
    status_code = 502
    code = ErrorCode.GENERATION_FAILED
    message = "O modelo devolveu uma resposta que nao pode ser interpretada."


class RespostaModelo(BaseModel):
    """Forma exata do JSON que o modelo deve devolver (camada 3)."""

    answer: str
    citations: list[str] = []
    insufficient_evidence: bool = False
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class CitacaoFinal:
    identificador: str
    rank: int
    hit: Hit


@dataclass(frozen=True, slots=True)
class RespostaRag:
    query_id: uuid.UUID
    status: QueryStatus
    answer: str
    citations: list[CitacaoFinal]
    confidence: float | None
    insufficient_evidence: bool
    gate: DecisaoGate
    chunks_retrieved: int
    retrieval_ms: int
    generation_ms: int | None
    total_ms: int
    model: str | None
    citacoes_invalidas: list[str] = field(default_factory=list)


class RagService:
    def __init__(
        self,
        *,
        settings: Settings,
        search: SearchService,
        generation: GenerationClient | None,
        queries: QueryRepository,
        session: AsyncSession,
    ) -> None:
        self._settings = settings
        self._search = search
        self._generation = generation
        self._queries = queries
        # Recebida so para o commit explicito da consulta FAILED — ver `answer`.
        self._session = session

    async def answer(self, pergunta: str, *, user_id: uuid.UUID) -> RespostaRag:
        inicio = time.perf_counter()
        pergunta = pergunta.strip()

        # --- 1. Retrieval ------------------------------------------------------
        resultado = await self._search.search(pergunta, mode=SearchMode.HYBRID)
        hits = resultado.hits

        # --- 2. Gate -----------------------------------------------------------
        decisao = avaliar_gate(hits, self._settings)
        if not decisao.aprovado:
            total_ms = _ms(inicio)
            query = await self._persistir(
                user_id=user_id,
                pergunta=pergunta,
                status=QueryStatus.INSUFFICIENT_EVIDENCE,
                embedding=resultado.embedding,
                hits=hits,
                decisao=decisao,
                confidence=None,
                retrieval_ms=resultado.retrieval_ms,
                generation_ms=None,
                total_ms=total_ms,
                model=None,
                tokens=(None, None),
                answer_text=RECUSA_CANONICA,
                insufficient=True,
                citations=[],
                raw={"gate": decisao.detalhes},
                error_code=None,
            )
            logger.info(
                "rag_refused_by_gate",
                query_id=str(query.id),
                reason=decisao.motivo,
                top_similarity=decisao.top_similarity,
                support=decisao.suporte,
            )
            return RespostaRag(
                query_id=query.id,
                status=QueryStatus.INSUFFICIENT_EVIDENCE,
                answer=RECUSA_CANONICA,
                citations=[],
                confidence=None,
                insufficient_evidence=True,
                gate=decisao,
                chunks_retrieved=len(hits),
                retrieval_ms=resultado.retrieval_ms,
                generation_ms=None,
                total_ms=total_ms,
                model=None,
            )

        # --- 3. Contexto e geracao ---------------------------------------------
        if self._generation is None:
            from app.integrations.gemini.client import GeminiNotConfiguredError

            raise GeminiNotConfiguredError

        contexto = montar_contexto(hits, orcamento_tokens=self._settings.rag_context_token_budget)
        mensagem = montar_mensagem(pergunta, contexto)

        inicio_geracao = time.perf_counter()
        try:
            gerado = await self._generation.generate_json(
                system=SYSTEM_PROMPT,
                user=mensagem,
                response_schema=RESPONSE_SCHEMA,
                temperature=self._settings.rag_generation_temperature,
            )
            modelo = interpretar_resposta(gerado.text)
        except (GeminiError, GenerationFailedError) as exc:
            generation_ms = _ms(inicio_geracao)
            await self._persistir(
                user_id=user_id,
                pergunta=pergunta,
                status=QueryStatus.FAILED,
                embedding=resultado.embedding,
                hits=hits,
                decisao=decisao,
                confidence=None,
                retrieval_ms=resultado.retrieval_ms,
                generation_ms=generation_ms,
                total_ms=_ms(inicio),
                model=self._generation.generation_model,
                tokens=(None, None),
                answer_text=None,
                insufficient=False,
                citations=[],
                raw={"gate": decisao.detalhes, "error": exc.code.value},
                error_code=exc.code.value,
            )
            # Commit ANTES de propagar. A excecao vai subir ate `get_db`, que faz
            # rollback — e o registro da falha sumiria junto. Uma falha que nao fica
            # registrada nao aparece no Intelligence, e a taxa de erro do modelo
            # seria sistematicamente subestimada. Mesmo bug (e mesma correcao) da
            # deteccao de reuso de refresh token na Fase 3.
            await self._session.commit()
            logger.warning("rag_generation_failed", error_code=exc.code.value)
            raise
        generation_ms = _ms(inicio_geracao)

        # --- 4. Validacao de citacoes -----------------------------------------
        texto, validas, invalidas = validar_citacoes(modelo, contexto)
        insuficiente = modelo.insufficient_evidence or not validas
        if insuficiente and not modelo.insufficient_evidence:
            # O modelo respondeu sem citar nada valido: tratado como recusa. Uma
            # afirmacao sem fonte nao e melhor que nenhuma afirmacao — e pior,
            # porque parece resposta.
            logger.warning("rag_answer_without_valid_citations", invalid=invalidas)

        # --- 5. Confianca calculada -------------------------------------------
        confianca = calcular_confianca(
            top_similarity=decisao.top_similarity,
            suporte=decisao.suporte,
            citacoes_validas=len(validas),
            citacoes_invalidas=len(invalidas),
            insuficiente=insuficiente,
            minimo_topo=self._settings.rag_min_top_score,
        )

        status = QueryStatus.INSUFFICIENT_EVIDENCE if insuficiente else QueryStatus.SUCCESS
        total_ms = _ms(inicio)
        query = await self._persistir(
            user_id=user_id,
            pergunta=pergunta,
            status=status,
            embedding=resultado.embedding,
            hits=hits,
            decisao=decisao,
            confidence=confianca,
            retrieval_ms=resultado.retrieval_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            model=gerado.model,
            tokens=(gerado.prompt_tokens, gerado.completion_tokens),
            answer_text=texto if validas else RECUSA_CANONICA,
            insufficient=insuficiente,
            citations=validas,
            raw={
                "model": modelo.model_dump(),
                "invalid_citations": invalidas,
                "gate": decisao.detalhes,
                "context_tokens": contexto.tokens,
                "context_blocks": len(contexto.blocos),
                "context_dropped": contexto.descartados,
                "finish_reason": gerado.finish_reason,
            },
            error_code=None,
        )

        logger.info(
            "rag_answered",
            query_id=str(query.id),
            status=status.value,
            citations=len(validas),
            invalid_citations=len(invalidas),
            confidence=confianca,
            retrieval_ms=resultado.retrieval_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            prompt_tokens=gerado.prompt_tokens,
            completion_tokens=gerado.completion_tokens,
        )
        return RespostaRag(
            query_id=query.id,
            status=status,
            answer=texto if validas else RECUSA_CANONICA,
            citations=validas,
            confidence=confianca,
            insufficient_evidence=insuficiente,
            gate=decisao,
            chunks_retrieved=len(hits),
            retrieval_ms=resultado.retrieval_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            model=gerado.model,
            citacoes_invalidas=invalidas,
        )

    # --- Persistencia -----------------------------------------------------------

    async def _persistir(
        self,
        *,
        user_id: uuid.UUID,
        pergunta: str,
        status: QueryStatus,
        embedding: list[float] | None,
        hits: list[Hit],
        decisao: DecisaoGate,
        confidence: float | None,
        retrieval_ms: int,
        generation_ms: int | None,
        total_ms: int,
        model: str | None,
        tokens: tuple[int | None, int | None],
        answer_text: str | None,
        insufficient: bool,
        citations: list[CitacaoFinal],
        raw: dict[str, Any],
        error_code: str | None,
    ) -> Query:
        query = Query(
            user_id=user_id,
            question=pergunta,
            status=status,
            embedding=embedding,
            chunks_retrieved=len(hits),
            top_score=decisao.top_similarity,
            confidence=confidence,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            model=model,
            prompt_tokens=tokens[0],
            completion_tokens=tokens[1],
            error_code=error_code,
        )
        if answer_text is not None:
            query.answer = Answer(
                content=answer_text,
                insufficient_evidence=insufficient,
                raw_response=raw,
                citations=[
                    Citation(
                        document_chunk_id=c.hit.chunk.chunk_id,
                        document_version_id=c.hit.chunk.version_id,
                        rank=c.rank,
                        score=c.hit.similarity if c.hit.similarity is not None else c.hit.score,
                    )
                    for c in citations
                ],
            )
        return await self._queries.create(query)


# --- Funcoes puras ----------------------------------------------------------------


def interpretar_resposta(texto: str) -> RespostaModelo:
    """Le o JSON do modelo. Tolera cerca de codigo; nao tolera outra coisa."""
    bruto = texto.strip()
    if bruto.startswith("```"):
        bruto = bruto.strip("`")
        if bruto.lower().startswith("json"):
            bruto = bruto[4:]
    try:
        return RespostaModelo.model_validate(json.loads(bruto))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("rag_unparseable_response", error_type=type(exc).__name__)
        raise GenerationFailedError from exc


def validar_citacoes(
    modelo: RespostaModelo, contexto: Contexto
) -> tuple[str, list[CitacaoFinal], list[str]]:
    """Confere cada identificador citado contra o contexto que foi enviado.

    Fontes: o campo `citations` E os marcadores `[Cn]` no texto — o modelo as vezes
    cita no texto e esquece a lista, ou o contrario. Identificador desconhecido e
    removido do texto e registrado; nunca vira citacao.

    Devolve as citacoes na ordem em que aparecem no texto (o que o leitor ve
    primeiro e a fonte principal), com as citadas so na lista no fim.
    """
    conhecidos = contexto.identificadores
    por_id = {b.identificador: b.hit for b in contexto.blocos}

    no_texto = _MARCADOR_CITACAO.findall(modelo.answer)
    na_lista = [c.strip().upper() for c in modelo.citations if c and c.strip()]

    ordem: list[str] = []
    invalidas: list[str] = []
    for identificador in [*no_texto, *na_lista]:
        if identificador in conhecidos:
            if identificador not in ordem:
                ordem.append(identificador)
        elif identificador not in invalidas:
            invalidas.append(identificador)

    # Renumera os marcadores na ordem de aparicao: o que o leitor ve como [C1] e a
    # citacao de rank 0, sempre. Sem isso, o historico (que reconstroi os
    # identificadores a partir do rank) mostraria [C3] no texto e "C1" na lista.
    renumeracao = {antigo: f"C{novo + 1}" for novo, antigo in enumerate(ordem)}

    def _substituir(m: re.Match[str]) -> str:
        novo = renumeracao.get(m.group(1))
        return f"[{novo}]" if novo else ""  # invalida: removida

    texto = _MARCADOR_CITACAO.sub(_substituir, modelo.answer)
    texto = re.sub(r"[ \t]+([.,;:!?])", r"\1", texto)  # "prazo [C9]." -> "prazo."
    texto = re.sub(r"[ \t]{2,}", " ", texto).strip()

    validas = [
        CitacaoFinal(identificador=renumeracao[antigo], rank=rank, hit=por_id[antigo])
        for rank, antigo in enumerate(ordem)
    ]
    return texto, validas, invalidas


def calcular_confianca(
    *,
    top_similarity: float | None,
    suporte: int,
    citacoes_validas: int,
    citacoes_invalidas: int,
    insuficiente: bool,
    minimo_topo: float,
) -> float:
    """Confianca exibida — calculada, nunca auto-reportada (ADR-0008, camada 5).

    Tres sinais observaveis, cada um em [0, 1]:

    - forca do retrieval: quao acima do gate ficou o melhor chunk;
    - suporte: quantos chunks sustentam o tema (satura em 3);
    - disciplina de citacao: fracao das citacoes que eram validas, penalizando
      um modelo que inventa fontes mesmo quando acerta algumas.

    Os pesos sao heuristica declarada, nao calibracao estatistica; com feedback
    acumulado (Fase 9) e possivel ajusta-los contra a taxa de avaliacao positiva.
    """
    if insuficiente or citacoes_validas == 0 or top_similarity is None:
        return 0.0

    forca = min(1.0, max(0.0, (top_similarity - minimo_topo) / max(1e-6, 1.0 - minimo_topo)))
    suporte_norm = min(1.0, suporte / 3)
    total_citacoes = citacoes_validas + citacoes_invalidas
    disciplina = citacoes_validas / total_citacoes if total_citacoes else 0.0

    confianca = 0.5 * forca + 0.25 * suporte_norm + 0.25 * disciplina
    return round(min(1.0, max(0.0, confianca)), 3)


def _ms(desde: float) -> int:
    return int((time.perf_counter() - desde) * 1000)
