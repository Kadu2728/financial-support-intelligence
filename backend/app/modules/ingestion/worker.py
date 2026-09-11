"""Worker de ingestao (ADR-0004).

Roda como task asyncio dentro do processo da API. Um deploy so, sem broker, sem
segundo servico — o que um monolito modular pede.

**Tres transacoes por job, de proposito:**

1. *Claim*: `FOR UPDATE SKIP LOCKED` + status RUNNING, commit imediato. Outro worker
   (ou outra instancia) ve o job como tomado.
2. *Processamento*: extracao, embeddings e gravacao. A transacao de escrita so
   abre no fim — ver `IngestionService`.
3. *Falha*: registrada numa sessao NOVA. A sessao do processamento pode estar em
   estado de rollback, e um UPDATE nela seria descartado junto — o mesmo bug que a
   deteccao de reuso de refresh token teve na Fase 3.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Collection
from datetime import timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.integrations.gemini.client import EmbeddingClient
from app.integrations.storage.base import StorageBackend
from app.modules.documents.repository import DocumentChunkRepository, DocumentVersionRepository
from app.modules.ingestion.models import ProcessingJob
from app.modules.ingestion.repository import ProcessingJobRepository
from app.modules.ingestion.service import IngestionService

logger = structlog.get_logger(__name__)

# Erros em que retentar e inutil: o arquivo nao muda entre tentativas.
_PERMANENTES = frozenset(
    {
        ErrorCode.EXTRACTION_FAILED,
        ErrorCode.NO_TEXT_LAYER,
        ErrorCode.UNSUPPORTED_FILE_TYPE,
    }
)


class IngestionWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        storage: StorageBackend,
        embeddings: EmbeddingClient,
    ) -> None:
        self._settings = settings
        self._sessions = session_factory
        self._storage = storage
        self._embeddings = embeddings

    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("worker_started", poll_s=self._settings.worker_poll_interval_seconds)
        await self.recover_stale()

        while not stop.is_set():
            try:
                processou = await self.run_once()
            except Exception:
                # O loop nunca morre por causa de um job. Um erro aqui e falha de
                # infraestrutura (banco fora), nao do documento — espera e tenta.
                logger.exception("worker_iteration_failed")
                processou = False

            if not processou:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        stop.wait(), timeout=self._settings.worker_poll_interval_seconds
                    )

        logger.info("worker_stopped")

    async def recover_stale(self) -> None:
        async with self._sessions() as session:
            jobs = ProcessingJobRepository(session)
            devolvidos = await jobs.requeue_stale(
                older_than=timedelta(minutes=self._settings.worker_stale_after_minutes)
            )
            await session.commit()
        if devolvidos:
            logger.warning("worker_requeued_stale_jobs", count=devolvidos)

    async def run_once(self, *, version_ids: Collection[uuid.UUID] | None = None) -> bool:
        """Processa no maximo um job. Devolve False se a fila estava vazia."""
        reivindicado = await self._claim(version_ids)
        if reivindicado is None:
            return False

        job_id, version_id = reivindicado
        log = logger.bind(job_id=str(job_id), version_id=str(version_id))

        try:
            await self._process(version_id, job_id)
        except Exception as exc:
            await self._register_failure(job_id, version_id, exc, log)
        else:
            log.info("job_completed")

        return True

    # --- Transacao 1: claim --------------------------------------------------

    async def _claim(
        self, version_ids: Collection[uuid.UUID] | None
    ) -> tuple[uuid.UUID, uuid.UUID] | None:
        async with self._sessions() as session:
            jobs = ProcessingJobRepository(session)
            versions = DocumentVersionRepository(session)

            job: ProcessingJob | None = await jobs.claim(version_ids=version_ids)
            if job is None:
                await session.rollback()
                return None

            await versions.mark_processing(job.document_version_id)
            await session.commit()
            return job.id, job.document_version_id

    # --- Transacao 2: processamento -----------------------------------------

    async def _process(self, version_id: uuid.UUID, job_id: uuid.UUID) -> None:
        async with self._sessions() as session:
            versions = DocumentVersionRepository(session)
            versao = await versions.get(version_id)
            if versao is None:
                raise AppError("Versao do job nao existe mais.")

            service = IngestionService(
                storage=self._storage,
                embeddings=self._embeddings,
                versions=versions,
                chunks=DocumentChunkRepository(session),
            )
            try:
                await service.processar_versao(versao)
                await ProcessingJobRepository(session).complete(job_id)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # --- Transacao 3: falha ---------------------------------------------------

    async def _register_failure(
        self,
        job_id: uuid.UUID,
        version_id: uuid.UUID,
        exc: Exception,
        log: structlog.stdlib.BoundLogger,
    ) -> None:
        if isinstance(exc, AppError):
            codigo, detalhe = exc.code, exc.message
        else:
            # Excecao inesperada: o tipo vai para o registro, a mensagem completa
            # so para o log — pode conter caminho, connection string, o que for.
            codigo, detalhe = ErrorCode.INTERNAL_ERROR, f"Erro inesperado ({type(exc).__name__})."

        permanente = codigo in _PERMANENTES
        log.warning(
            "job_failed",
            error_code=codigo.value,
            permanent=permanente,
            error_type=type(exc).__name__,
            exc_info=not isinstance(exc, AppError),
        )

        async with self._sessions() as session:
            jobs = ProcessingJobRepository(session)
            versions = DocumentVersionRepository(session)

            esgotado = await jobs.fail(job_id, error=detalhe, permanent=permanente)
            if esgotado:
                await versions.mark_failed(version_id, error_code=codigo.value, detail=detalhe)
            else:
                # Volta a PENDING: a tela de admin mostra "na fila", nao "processando"
                # — que seria mentira ate o proximo claim.
                await versions.mark_pending(version_id)
            await session.commit()
