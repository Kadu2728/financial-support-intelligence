from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.documents.models import Document, DocumentChunk, DocumentStatus, DocumentVersion


@dataclass(frozen=True, slots=True)
class DocumentFilters:
    status: DocumentStatus | None = None
    category: str | None = None
    termo: str | None = None


@dataclass(frozen=True, slots=True)
class Page:
    itens: Sequence[Document]
    total: int


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _base(self) -> Select[tuple[Document]]:
        # Soft delete nunca e opcional na leitura: um documento excluido nao pode
        # reaparecer em lista nenhuma.
        return select(Document).where(Document.deleted_at.is_(None))

    async def list_page(self, *, filtros: DocumentFilters, pagina: int, tamanho: int) -> Page:
        consulta = self._base()

        if filtros.category:
            consulta = consulta.where(Document.category == filtros.category)

        if filtros.termo:
            # `ilike` com curinga nos dois lados, acelerado pelo indice trigram
            # (ix_documents_title_trgm). Um btree comum nao ajudaria aqui.
            consulta = consulta.where(Document.title.ilike(f"%{filtros.termo}%"))

        if filtros.status is not None:
            consulta = consulta.where(
                Document.id.in_(
                    select(DocumentVersion.document_id).where(
                        DocumentVersion.is_current.is_(True),
                        DocumentVersion.status == filtros.status,
                    )
                )
            )

        total = await self._session.scalar(select(func.count()).select_from(consulta.subquery()))

        # `selectinload` explicito: os relationships usam lazy="raise", entao sem isto
        # o acesso a `versions` levantaria em vez de disparar N+1 silencioso.
        resultado = await self._session.execute(
            consulta.options(selectinload(Document.versions))
            .order_by(Document.updated_at.desc())
            .offset((pagina - 1) * tamanho)
            .limit(tamanho)
        )

        return Page(itens=list(resultado.scalars().all()), total=total or 0)

    async def get(self, document_id: uuid.UUID) -> Document | None:
        resultado = await self._session.execute(
            self._base().where(Document.id == document_id).options(selectinload(Document.versions))
        )
        return resultado.scalar_one_or_none()

    async def create(
        self,
        *,
        title: str,
        description: str | None,
        category: str | None,
        uploaded_by: uuid.UUID,
    ) -> Document:
        documento = Document(
            title=title,
            description=description,
            category=category,
            uploaded_by=uploaded_by,
        )
        self._session.add(documento)
        await self._session.flush()
        return documento

    async def soft_delete(self, document_id: uuid.UUID) -> bool:
        """Marca como excluido preservando o registro.

        As citacoes historicas apontam para versoes deste documento e precisam
        continuar resolviveis (ADR-0005). A FK de `citations` e RESTRICT justamente
        para impedir a exclusao fisica.
        """
        resultado = await self._session.execute(
            update(Document)
            .where(Document.id == document_id, Document.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC))
        )
        return bool(cast("CursorResult[Any]", resultado).rowcount)

    async def touch(self, document_id: uuid.UUID) -> None:
        """Atualiza `updated_at` para que a lista reordene ao subir nova versao."""
        await self._session.execute(
            update(Document).where(Document.id == document_id).values(updated_at=datetime.now(UTC))
        )


class DocumentVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, version_id: uuid.UUID) -> DocumentVersion | None:
        return await self._session.get(DocumentVersion, version_id)

    async def get_current(self, document_id: uuid.UUID) -> DocumentVersion | None:
        resultado = await self._session.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.is_current.is_(True),
            )
        )
        return resultado.scalar_one_or_none()

    async def find_by_checksum(self, checksum: str) -> DocumentVersion | None:
        resultado = await self._session.execute(
            select(DocumentVersion).where(DocumentVersion.checksum_sha256 == checksum)
        )
        return resultado.scalar_one_or_none()

    async def next_version_number(self, document_id: uuid.UUID) -> int:
        atual = await self._session.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.document_id == document_id
            )
        )
        return (atual or 0) + 1

    async def create(
        self,
        *,
        document_id: uuid.UUID,
        version_number: int,
        original_filename: str,
        mime_type: str,
        file_size_bytes: int,
        checksum_sha256: str,
        storage_key: str,
    ) -> DocumentVersion:
        versao = DocumentVersion(
            document_id=document_id,
            version_number=version_number,
            status=DocumentStatus.PENDING,
            # `is_current` so vira True quando o processamento termina (Fase 5). Marcar
            # agora exporia a versao a busca antes de existirem chunks, e o documento
            # apareceria como disponivel sem nenhum conteudo indexado.
            is_current=False,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size_bytes=file_size_bytes,
            checksum_sha256=checksum_sha256,
            storage_key=storage_key,
        )
        self._session.add(versao)
        await self._session.flush()
        return versao

    async def mark_failed(self, version_id: uuid.UUID, *, error_code: str, detail: str) -> None:
        await self._session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == version_id)
            .values(
                status=DocumentStatus.FAILED,
                error_code=error_code,
                # Truncado: mensagem de excecao pode ser enorme e vai para a tela.
                error_detail=detail[:2000],
                processed_at=datetime.now(UTC),
            )
        )

    async def mark_pending(self, version_id: uuid.UUID) -> None:
        await self._session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == version_id)
            .values(status=DocumentStatus.PENDING)
        )

    async def mark_processing(self, version_id: uuid.UUID) -> None:
        await self._session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == version_id)
            .values(status=DocumentStatus.PROCESSING, error_code=None, error_detail=None)
        )

    async def promote_to_current(
        self, versao: DocumentVersion, *, page_count: int | None, chunk_count: int
    ) -> None:
        """Torna a versao corrente e rebaixa a anterior, na mesma transacao.

        A ordem importa: o indice parcial unico `uq_document_versions_current` recusa
        duas versoes correntes do mesmo documento, entao a anterior precisa perder o
        flag ANTES de esta receber. Com `autoflush=False` os dois UPDATEs precisam de
        flush explicito entre eles.
        """
        await self._session.execute(
            update(DocumentVersion)
            .where(
                DocumentVersion.document_id == versao.document_id,
                DocumentVersion.id != versao.id,
                DocumentVersion.is_current.is_(True),
            )
            .values(is_current=False, status=DocumentStatus.SUPERSEDED)
        )
        await self._session.flush()

        versao.status = DocumentStatus.READY
        versao.is_current = True
        versao.page_count = page_count
        versao.chunk_count = chunk_count
        versao.error_code = None
        versao.error_detail = None
        versao.processed_at = datetime.now(UTC)
        await self._session.flush()


class DocumentChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_version(
        self, version_id: uuid.UUID, chunks: Sequence[DocumentChunk]
    ) -> None:
        """Substitui todos os chunks da versao.

        Reprocessar uma versao (extrator corrigido, modelo de embedding trocado)
        precisa apagar os chunks antigos, senao a busca devolveria o mesmo trecho
        duas vezes. A FK RESTRICT de `citations` bloqueia a exclusao de um chunk ja
        citado — nesse caso o reprocessamento falha de forma visivel, que e o
        comportamento correto: uma citacao historica nao pode ficar orfa.
        """
        await self._session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_version_id == version_id)
        )
        self._session.add_all(chunks)
        await self._session.flush()

    async def count_for_version(self, version_id: uuid.UUID) -> int:
        total = await self._session.scalar(
            select(func.count()).where(DocumentChunk.document_version_id == version_id)
        )
        return total or 0
