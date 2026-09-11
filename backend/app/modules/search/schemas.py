from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.modules.search.service import Hit, SearchMode, SearchResult


class SearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    mode: SearchMode = SearchMode.HYBRID
    top_k: int = Field(default=8, ge=1, le=20)


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    version_id: uuid.UUID
    section_path: str | None
    section_label: str | None
    page_number: int | None
    content: str
    char_start: int
    char_end: int
    # Score de fusao (RRF) — so faz sentido para ORDENAR; nao e probabilidade.
    score: float
    # Similaridade cosine em [0, 1], quando a perna semantica participou.
    similarity: float | None
    semantic_rank: int | None
    lexical_rank: int | None

    @classmethod
    def from_hit(cls, hit: Hit) -> SearchHit:
        c = hit.chunk
        return cls(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            document_title=c.document_title,
            version_id=c.version_id,
            section_path=c.section_path,
            section_label=c.section_label,
            page_number=c.page_number,
            content=c.content,
            char_start=c.char_start,
            char_end=c.char_end,
            score=hit.score,
            similarity=c.similarity,
            semantic_rank=hit.semantic_rank,
            lexical_rank=hit.lexical_rank,
        )


class SearchResponse(BaseModel):
    mode: SearchMode
    hits: list[SearchHit]
    retrieval_ms: int
    top_similarity: float | None

    @classmethod
    def from_result(cls, resultado: SearchResult) -> SearchResponse:
        return cls(
            mode=resultado.mode,
            hits=[SearchHit.from_hit(h) for h in resultado.hits],
            retrieval_ms=resultado.retrieval_ms,
            top_similarity=resultado.top_similarity,
        )
