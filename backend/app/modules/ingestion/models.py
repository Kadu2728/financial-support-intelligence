"""Fila de processamento.

Esta tabela E a fila. Consumida com `FOR UPDATE SKIP LOCKED`, dispensa broker externo e
ganha atomicidade de graca: criar a versao do documento e enfileirar o job acontecem na
mesma transacao. Justificativa em docs/adr/0004-fila-em-postgres.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, uuid_pk

if TYPE_CHECKING:
    from app.modules.documents.models import DocumentVersion


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobType(StrEnum):
    INGEST = "INGEST"


job_status_enum = Enum(
    JobStatus,
    name="job_status",
    values_callable=lambda enum: [member.value for member in enum],
)

job_type_enum = Enum(
    JobType,
    name="job_type",
    values_callable=lambda enum: [member.value for member in enum],
)


class ProcessingJob(Base, CreatedAtMixin):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )

    job_type: Mapped[JobType] = mapped_column(job_type_enum, nullable=False, default=JobType.INGEST)
    status: Mapped[JobStatus] = mapped_column(
        job_status_enum, nullable=False, default=JobStatus.PENDING
    )

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    version: Mapped[DocumentVersion] = relationship(back_populates="jobs", lazy="raise")

    __table_args__ = (
        # Indice de claim do worker. Parcial e coberto: so as linhas elegiveis, na ordem
        # em que serao consumidas. A tabela cresce indefinidamente com jobs concluidos,
        # e sem o filtro parcial o indice cresceria junto sem necessidade.
        Index(
            "ix_processing_jobs_claimable",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        # Deteccao de jobs travados: RUNNING com started_at antigo indica que o processo
        # morreu no meio. Sem isso, nao ha como distinguir travado de lento.
        Index(
            "ix_processing_jobs_running",
            "started_at",
            postgresql_where=text("status = 'RUNNING'"),
        ),
        Index("ix_processing_jobs_version", "document_version_id"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
    )

    def __repr__(self) -> str:
        return f"<ProcessingJob {self.job_type.value} {self.status.value} attempts={self.attempts}>"
