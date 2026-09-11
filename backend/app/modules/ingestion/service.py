"""Pipeline de ingestao: arquivo -> chunks indexados.

    storage.get -> extrair -> normalizar -> dividir -> embed -> gravar

Duas propriedades sao inegociaveis:

1. **Atomicidade da gravacao.** Chunks, `is_current` e o status READY entram na mesma
   transacao. Nao existe estado em que a versao esta READY sem chunks, ou com chunks
   mas ainda PENDING — a busca so enxerga a versao quando ela esta completa.

2. **Embeddings antes da transacao.** A chamada ao Gemini e a parte lenta e a que mais
   falha. Ela acontece com a sessao ociosa; a transacao de escrita so abre quando todos
   os vetores ja estao em memoria. Segurar uma conexao do Neon durante dezenas de
   chamadas HTTP esgotaria o pool pequeno do plano gratuito.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import structlog

from app.core.errors import AppError, ErrorCode
from app.integrations.gemini.client import EmbeddingClient, GeminiError, TaskType
from app.integrations.storage.base import ObjectNotFound, StorageBackend
from app.modules.documents.models import DocumentChunk, DocumentVersion
from app.modules.documents.repository import DocumentChunkRepository, DocumentVersionRepository
from app.modules.documents.validation import MIME_POR_FORMATO, DocumentFormat
from app.modules.ingestion.chunking import Chunk, dividir
from app.modules.ingestion.extractors.base import TextExtractor, TextoExtraido
from app.modules.ingestion.extractors.docx import DocxExtractor
from app.modules.ingestion.extractors.pdf import PdfExtractor
from app.modules.ingestion.extractors.plaintext import MarkdownExtractor, PlainTextExtractor
from app.modules.ingestion.normalizer import normalizar

logger = structlog.get_logger(__name__)

_EXTRATOR_POR_MIME: dict[str, TextExtractor] = {
    MIME_POR_FORMATO[DocumentFormat.PDF]: PdfExtractor(),
    MIME_POR_FORMATO[DocumentFormat.DOCX]: DocxExtractor(),
    MIME_POR_FORMATO[DocumentFormat.MARKDOWN]: MarkdownExtractor(),
    MIME_POR_FORMATO[DocumentFormat.TEXT]: PlainTextExtractor(),
}


class EmptyDocumentError(AppError):
    status_code = 422
    code = ErrorCode.EXTRACTION_FAILED
    message = "O documento nao contem texto aproveitavel."


@dataclass(frozen=True, slots=True)
class ResultadoIngestao:
    version_id: uuid.UUID
    chunks: int
    paginas: int | None
    extracao_ms: int
    embedding_ms: int
    gravacao_ms: int


@dataclass(frozen=True, slots=True)
class MaterialIndexavel:
    """Tudo que o pipeline produz ANTES de tocar no banco."""

    chunks: list[Chunk]
    vetores: list[list[float]]
    paginas: int | None
    extracao_ms: int
    embedding_ms: int


class IngestionService:
    def __init__(
        self,
        *,
        storage: StorageBackend,
        embeddings: EmbeddingClient,
        versions: DocumentVersionRepository,
        chunks: DocumentChunkRepository,
    ) -> None:
        self._storage = storage
        self._embeddings = embeddings
        self._versions = versions
        self._chunks = chunks

    # --- Etapas puras (sem banco) ------------------------------------------

    def preparar(self, conteudo: bytes, *, mime_type: str) -> tuple[list[Chunk], int | None]:
        """Extrai, normaliza e divide. Sincrono e sem I/O: testavel com bytes."""
        extrator = _EXTRATOR_POR_MIME.get(mime_type)
        if extrator is None:
            raise AppError(
                f"Sem extrator para {mime_type}.",
                details={"mime_type": mime_type},
            )

        extraido: TextoExtraido = extrator.extrair(conteudo)
        if extraido.vazio:
            raise EmptyDocumentError

        documento = normalizar(extraido)
        chunks = dividir(documento)
        if not chunks:
            raise EmptyDocumentError

        return chunks, documento.total_paginas

    async def materializar(self, conteudo: bytes, *, mime_type: str) -> MaterialIndexavel:
        inicio = time.perf_counter()
        chunks, paginas = self.preparar(conteudo, mime_type=mime_type)
        extracao_ms = int((time.perf_counter() - inicio) * 1000)

        inicio = time.perf_counter()
        vetores = await self._embeddings.embed(
            [c.texto for c in chunks], task_type=TaskType.RETRIEVAL_DOCUMENT
        )
        embedding_ms = int((time.perf_counter() - inicio) * 1000)

        if len(vetores) != len(chunks):
            # O cliente ja valida isto, mas o invariante e critico o bastante para
            # ser conferido tambem aqui: um desalinhamento gravaria o vetor de um
            # trecho no registro de outro, e a busca devolveria citacoes erradas
            # sem nenhum sinal de falha.
            raise GeminiError("Numero de embeddings diferente do numero de chunks.")

        return MaterialIndexavel(
            chunks=chunks,
            vetores=vetores,
            paginas=paginas,
            extracao_ms=extracao_ms,
            embedding_ms=embedding_ms,
        )

    # --- Orquestracao -------------------------------------------------------

    async def processar_versao(self, versao: DocumentVersion) -> ResultadoIngestao:
        """Executa o pipeline completo para uma versao ja marcada como PROCESSING.

        Quem chama controla a transacao (o worker). Este metodo so garante que tudo
        que escreve no banco esta agrupado no fim, depois do trabalho lento.
        """
        try:
            conteudo = await self._storage.get(versao.storage_key)
        except ObjectNotFound as exc:
            raise AppError(
                "Arquivo da versao nao encontrado no storage.",
                details={"storage_key": versao.storage_key},
            ) from exc

        material = await self.materializar(conteudo, mime_type=versao.mime_type)

        inicio = time.perf_counter()
        registros = [
            DocumentChunk(
                document_version_id=versao.id,
                chunk_index=chunk.indice,
                content=chunk.texto,
                content_tokens=chunk.tokens,
                section_path=chunk.section_path,
                section_label=(chunk.section_label or "")[:64] or None,
                page_number=chunk.pagina,
                char_start=chunk.inicio,
                char_end=chunk.fim,
                embedding=vetor,
                embedding_model=self._embeddings.embedding_model,
            )
            for chunk, vetor in zip(material.chunks, material.vetores, strict=True)
        ]
        await self._chunks.replace_for_version(versao.id, registros)
        await self._versions.promote_to_current(
            versao, page_count=material.paginas, chunk_count=len(registros)
        )
        gravacao_ms = int((time.perf_counter() - inicio) * 1000)

        logger.info(
            "version_indexed",
            version_id=str(versao.id),
            document_id=str(versao.document_id),
            chunks=len(registros),
            pages=material.paginas,
            extract_ms=material.extracao_ms,
            embed_ms=material.embedding_ms,
            write_ms=gravacao_ms,
        )
        return ResultadoIngestao(
            version_id=versao.id,
            chunks=len(registros),
            paginas=material.paginas,
            extracao_ms=material.extracao_ms,
            embedding_ms=material.embedding_ms,
            gravacao_ms=gravacao_ms,
        )
