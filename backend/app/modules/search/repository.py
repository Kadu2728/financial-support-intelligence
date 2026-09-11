"""As duas pernas da busca hibrida, cada uma como uma consulta SQL (ADR-0002).

Ambas filtram por `is_current` e por documento nao excluido. O filtro fica AQUI, na
consulta, e nao no service: conteudo de versao antiga ou de documento excluido nunca
pode chegar ao ranking, e a unica forma de garantir isso e nao o ler.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Float, cast, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import FTS_CONFIG, Document, DocumentChunk, DocumentVersion

_PALAVRA = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ChunkRecuperado:
    """Tudo que a resposta precisa de um chunk, ja com o titulo do documento."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    version_id: uuid.UUID
    chunk_index: int
    section_path: str | None
    section_label: str | None
    page_number: int | None
    content: str
    content_tokens: int
    char_start: int
    char_end: int
    # Similaridade cosine com a pergunta. Calculada para TODOS os finalistas, mesmo os
    # que so a perna lexical trouxe — o gate de evidencia precisa de um numero
    # comparavel para cada um.
    similarity: float | None


class SearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _visiveis(self) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
        return (DocumentVersion.is_current.is_(True), Document.deleted_at.is_(None))

    async def semantic(
        self, embedding: Sequence[float], *, limit: int
    ) -> list[tuple[uuid.UUID, float]]:
        """Top-N por cosine. `<=>` e distancia; similaridade = 1 - distancia.

        O ORDER BY usa a mesma expressao do indice HNSW (`vector_cosine_ops`), que e
        a condicao para o planner usa-lo.
        """
        distancia = DocumentChunk.embedding.cosine_distance(list(embedding))
        consulta = (
            select(DocumentChunk.id, (literal(1.0) - distancia).label("similarity"))
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(*self._visiveis())
            .order_by(distancia)
            .limit(limit)
        )
        linhas = (await self._session.execute(consulta)).all()
        return [(linha[0], float(linha[1])) for linha in linhas]

    async def lexical(self, pergunta: str, *, limit: int) -> list[tuple[uuid.UUID, float]]:
        """Top-N por full-text.

        Primeiro tenta a consulta estrita (`websearch_to_tsquery`: todos os termos,
        respeita aspas). Uma pergunta em linguagem natural com seis termos raramente
        casa todos num chunk de 500 tokens, entao com resultado vazio cai para OR
        dos termos — e `ts_rank_cd` cuida de ordenar quem casa mais.
        """
        estrita = func.websearch_to_tsquery(FTS_CONFIG, pergunta)
        resultado = await self._lexical_com(estrita, limit)
        if resultado:
            return resultado

        termos = [t for t in _PALAVRA.findall(pergunta) if len(t) > 2]
        if not termos:
            return []
        frouxa = func.to_tsquery(FTS_CONFIG, " | ".join(termos))
        return await self._lexical_com(frouxa, limit)

    async def _lexical_com(self, tsquery: object, limit: int) -> list[tuple[uuid.UUID, float]]:
        rank = func.ts_rank_cd(DocumentChunk.tsv, tsquery)
        consulta = (
            select(DocumentChunk.id, cast(rank, Float).label("rank"))
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentChunk.tsv.op("@@")(tsquery), *self._visiveis())
            .order_by(text("rank DESC"), DocumentChunk.id)
            .limit(limit)
        )
        linhas = (await self._session.execute(consulta)).all()
        return [(linha[0], float(linha[1])) for linha in linhas]

    async def fetch(
        self, chunk_ids: Sequence[uuid.UUID], *, embedding: Sequence[float] | None
    ) -> dict[uuid.UUID, ChunkRecuperado]:
        """Carrega os finalistas com titulo do documento e, se houver embedding da
        pergunta, a similaridade de cada um."""
        if not chunk_ids:
            return {}

        colunas: list[object] = [
            DocumentChunk.id,
            Document.id,
            Document.title,
            DocumentVersion.id,
            DocumentChunk.chunk_index,
            DocumentChunk.section_path,
            DocumentChunk.section_label,
            DocumentChunk.page_number,
            DocumentChunk.content,
            DocumentChunk.content_tokens,
            DocumentChunk.char_start,
            DocumentChunk.char_end,
        ]
        if embedding is not None:
            colunas.append(literal(1.0) - DocumentChunk.embedding.cosine_distance(list(embedding)))
        else:
            colunas.append(literal(None))

        consulta = (
            select(*colunas)  # type: ignore[call-overload]
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentChunk.id.in_(list(chunk_ids)))
        )
        linhas = (await self._session.execute(consulta)).all()
        return {
            linha[0]: ChunkRecuperado(
                chunk_id=linha[0],
                document_id=linha[1],
                document_title=linha[2],
                version_id=linha[3],
                chunk_index=linha[4],
                section_path=linha[5],
                section_label=linha[6],
                page_number=linha[7],
                content=linha[8],
                content_tokens=linha[9],
                char_start=linha[10],
                char_end=linha[11],
                similarity=float(linha[12]) if linha[12] is not None else None,
            )
            for linha in linhas
        }
