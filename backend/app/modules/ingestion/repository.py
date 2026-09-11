"""Fila de processamento em PostgreSQL (ADR-0004).

Na Fase 4 apenas o enfileiramento e exercitado — o consumo entra na Fase 5. `claim` ja
esta aqui porque e a primitiva que define a corretude da fila, e escreve-la junto do
resto mantem o contrato visivel desde o inicio.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingestion.models import JobStatus, JobType, ProcessingJob


class ProcessingJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        document_version_id: uuid.UUID,
        job_type: JobType = JobType.INGEST,
        max_attempts: int = 3,
    ) -> ProcessingJob:
        job = ProcessingJob(
            document_version_id=document_version_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            attempts=0,
            max_attempts=max_attempts,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def claim(
        self, *, version_ids: Collection[uuid.UUID] | None = None
    ) -> ProcessingJob | None:
        """Reivindica um job para execucao.

        `FOR UPDATE SKIP LOCKED` e o que torna uma fila em Postgres correta sob
        concorrencia: linhas ja travadas por outro worker sao ignoradas em vez de
        bloquear o consumidor. Sem `SKIP LOCKED`, dois workers serializariam na mesma
        linha e a fila teria paralelismo de um.

        `version_ids` restringe o claim a versoes especificas. E o que permite ao
        CLI processar um documento sob demanda e aos testes de integracao dividirem
        a fila com dados reais sem consumi-los.
        """
        consulta = select(ProcessingJob).where(
            ProcessingJob.status == JobStatus.PENDING,
            ProcessingJob.attempts < ProcessingJob.max_attempts,
        )
        if version_ids is not None:
            consulta = consulta.where(ProcessingJob.document_version_id.in_(list(version_ids)))

        resultado = await self._session.execute(
            consulta.order_by(ProcessingJob.created_at).limit(1).with_for_update(skip_locked=True)
        )
        job = resultado.scalar_one_or_none()
        if job is None:
            return None

        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        await self._session.flush()
        return job

    async def complete(self, job_id: uuid.UUID) -> None:
        await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(status=JobStatus.COMPLETED, finished_at=datetime.now(UTC))
        )

    async def fail(self, job_id: uuid.UUID, *, error: str, permanent: bool = False) -> bool:
        """Marca a tentativa como falha. Devolve True se o job esgotou.

        Volta para PENDING enquanto houver tentativas restantes: o retry e a razao de a
        fila existir no banco em vez de so em memoria. Esgotadas as tentativas, o job
        para em FAILED e fica visivel para reprocessamento manual.

        `permanent` pula o retry. Um PDF escaneado nao ganha camada de texto na
        segunda tentativa; retentar so atrasa o aviso ao administrador.
        """
        job = await self._session.get(ProcessingJob, job_id)
        if job is None:
            return True

        esgotado = permanent or job.attempts >= job.max_attempts
        job.status = JobStatus.FAILED if esgotado else JobStatus.PENDING
        job.last_error = error[:2000]
        job.finished_at = datetime.now(UTC) if esgotado else None
        await self._session.flush()
        return esgotado

    async def requeue_stale(self, *, older_than: timedelta) -> int:
        """Devolve a fila jobs RUNNING abandonados por um processo que morreu.

        Sem isto, um deploy no meio de uma ingestao deixaria a versao presa em
        PROCESSING para sempre, sem erro e sem retry.
        """
        limite = datetime.now(UTC) - older_than
        resultado = await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.status == JobStatus.RUNNING, ProcessingJob.started_at < limite)
            .values(status=JobStatus.PENDING, started_at=None)
        )
        return int(cast("CursorResult[Any]", resultado).rowcount)

    async def requeue_for_version(self, document_version_id: uuid.UUID) -> ProcessingJob:
        """Reprocessamento sob demanda, disparado pelo administrador."""
        return await self.enqueue(document_version_id=document_version_id)
