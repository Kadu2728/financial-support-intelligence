"""Regra de negocio de documentos."""

from __future__ import annotations

import uuid
from typing import BinaryIO

import structlog
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError, ErrorCode, NotFoundError
from app.integrations.storage.base import (
    ObjectNotFound,
    StorageBackend,
    StorageError,
    build_storage_key,
)
from app.modules.documents.models import Document, DocumentStatus, DocumentVersion
from app.modules.documents.repository import (
    DocumentFilters,
    DocumentRepository,
    DocumentVersionRepository,
    Page,
)
from app.modules.documents.validation import ValidatedFile, read_and_validate
from app.modules.ingestion.repository import ProcessingJobRepository

logger = structlog.get_logger(__name__)


class DuplicateDocumentError(AppError):
    status_code = 409
    code = ErrorCode.DUPLICATE_DOCUMENT
    message = "Este arquivo ja foi enviado."


class DocumentNotReadyError(AppError):
    status_code = 409
    code = ErrorCode.DOCUMENT_NOT_READY
    message = "O documento ainda esta sendo processado."


class DocumentService:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        versions: DocumentVersionRepository,
        jobs: ProcessingJobRepository,
        storage: StorageBackend,
    ) -> None:
        self._documents = documents
        self._versions = versions
        self._jobs = jobs
        self._storage = storage

    # --- Leitura -----------------------------------------------------------

    async def list_documents(self, *, filtros: DocumentFilters, pagina: int, tamanho: int) -> Page:
        return await self._documents.list_page(filtros=filtros, pagina=pagina, tamanho=tamanho)

    async def get_document(self, document_id: uuid.UUID) -> Document:
        documento = await self._documents.get(document_id)
        if documento is None:
            raise NotFoundError("Documento nao encontrado.")
        return documento

    async def get_content(self, document_id: uuid.UUID) -> tuple[bytes, DocumentVersion]:
        """Devolve o arquivo original da versao corrente.

        E o que sustenta "abrir o documento utilizado" a partir de uma citacao.
        """
        documento = await self.get_document(document_id)
        versao = await self._versions.get_current(documento.id)

        if versao is None:
            # Sem versao corrente significa que nenhuma chegou a READY — o documento
            # esta em processamento ou falhou. Entregar a ultima assim mesmo permite
            # ao administrador conferir o que subiu e diagnosticar a falha.
            if not documento.versions:
                raise NotFoundError("Documento sem nenhuma versao.")
            versao = max(documento.versions, key=lambda v: v.version_number)

        try:
            conteudo = await self._storage.get(versao.storage_key)
        except ObjectNotFound as exc:
            # Registro sem arquivo: o caso classico do filesystem efemero (ADR-0007).
            # O erro precisa dizer isso, e nao "nao encontrado" generico.
            logger.error(
                "storage_object_missing",
                document_id=str(document_id),
                storage_key=versao.storage_key,
            )
            raise NotFoundError(
                "O arquivo deste documento nao esta disponivel no armazenamento."
            ) from exc

        return conteudo, versao

    # --- Escrita -----------------------------------------------------------

    async def create_document(
        self,
        *,
        title: str,
        description: str | None,
        category: str | None,
        filename: str,
        stream: BinaryIO,
        uploaded_by: uuid.UUID,
    ) -> tuple[Document, DocumentVersion]:
        arquivo = read_and_validate(stream, filename=filename)

        duplicata = await self._versions.find_by_checksum(arquivo.checksum_sha256)
        if duplicata is not None:
            # Barrar antes de gastar storage e, na Fase 5, chamadas de embedding.
            raise DuplicateDocumentError(
                "Este arquivo ja foi enviado anteriormente.",
                details={"document_id": str(duplicata.document_id)},
            )

        documento = await self._documents.create(
            title=title,
            description=description,
            category=category,
            uploaded_by=uploaded_by,
        )
        versao, job_id = await self._store_version(
            documento_id=documento.id,
            version_number=1,
            arquivo=arquivo,
            filename=filename,
        )

        logger.info(
            "document_created",
            document_id=str(documento.id),
            version_id=str(versao.id),
            job_id=str(job_id),
            formato=arquivo.formato.value,
            size_bytes=arquivo.size_bytes,
        )
        return documento, versao

    async def add_version(
        self, *, document_id: uuid.UUID, filename: str, stream: BinaryIO
    ) -> DocumentVersion:
        """Nova versao de um documento existente (ADR-0005).

        A versao corrente NAO e substituida aqui: continua servindo a busca ate que o
        processamento da nova termine. Trocar agora deixaria o documento indisponivel
        durante o processamento.
        """
        documento = await self.get_document(document_id)
        arquivo = read_and_validate(stream, filename=filename)

        duplicata = await self._versions.find_by_checksum(arquivo.checksum_sha256)
        if duplicata is not None:
            mesmo_documento = duplicata.document_id == document_id
            raise DuplicateDocumentError(
                "Esta versao e identica a uma ja enviada."
                if mesmo_documento
                else "Este arquivo ja existe em outro documento.",
                details={"document_id": str(duplicata.document_id)},
            )

        numero = await self._versions.next_version_number(documento.id)
        versao, job_id = await self._store_version(
            documento_id=documento.id,
            version_number=numero,
            arquivo=arquivo,
            filename=filename,
        )
        await self._documents.touch(documento.id)

        logger.info(
            "document_version_added",
            document_id=str(documento.id),
            version_id=str(versao.id),
            version_number=numero,
            job_id=str(job_id),
        )
        return versao

    async def delete_document(self, document_id: uuid.UUID) -> None:
        """Exclusao logica.

        O arquivo no storage NAO e apagado: citacoes historicas apontam para versoes
        deste documento, e o analista precisa continuar conseguindo abrir a fonte de
        uma resposta antiga. Remocao definitiva seria uma rotina de retencao separada,
        com decisao explicita.
        """
        if not await self._documents.soft_delete(document_id):
            raise NotFoundError("Documento nao encontrado.")
        logger.info("document_deleted", document_id=str(document_id))

    async def reprocess(self, document_id: uuid.UUID) -> uuid.UUID:
        """Re-enfileira a ultima versao. Caminho de recuperacao de um FAILED."""
        documento = await self.get_document(document_id)
        if not documento.versions:
            raise NotFoundError("Documento sem nenhuma versao.")

        alvo = max(documento.versions, key=lambda v: v.version_number)
        if alvo.status is DocumentStatus.PROCESSING:
            raise DocumentNotReadyError("Esta versao ja esta em processamento.")

        job = await self._jobs.requeue_for_version(alvo.id)
        alvo.status = DocumentStatus.PENDING
        alvo.error_code = None
        alvo.error_detail = None

        logger.info(
            "document_reprocess_requested",
            document_id=str(document_id),
            version_id=str(alvo.id),
            job_id=str(job.id),
        )
        return job.id

    # --- Interno -----------------------------------------------------------

    async def _store_version(
        self,
        *,
        documento_id: uuid.UUID,
        version_number: int,
        arquivo: ValidatedFile,
        filename: str,
    ) -> tuple[DocumentVersion, uuid.UUID]:
        """Grava o arquivo e registra versao e job.

        **Ordem deliberada: storage primeiro, banco depois.** O storage nao participa
        da transacao. Gravando o banco antes, uma falha no storage deixaria um registro
        apontando para um arquivo inexistente — o documento apareceria na lista e
        quebraria ao ser aberto. Na ordem inversa, o pior caso e um objeto orfao, que
        e inofensivo e removivel por rotina.
        """
        version_id = uuid.uuid4()
        chave = build_storage_key(
            document_id=documento_id, version_id=version_id, filename=filename
        )

        try:
            await self._storage.put(chave, arquivo.content, content_type=arquivo.mime_type)
        except StorageError as exc:
            logger.error("storage_put_failed", storage_key=chave, error=str(exc))
            raise UploadFailedError from exc

        try:
            versao = await self._versions.create(
                document_id=documento_id,
                version_number=version_number,
                original_filename=filename[:512],
                mime_type=arquivo.mime_type,
                file_size_bytes=arquivo.size_bytes,
                checksum_sha256=arquivo.checksum_sha256,
                storage_key=chave,
            )
            # Mesma transacao do INSERT da versao: nao existe estado em que a versao
            # exista sem job para processa-la (ADR-0004).
            job = await self._jobs.enqueue(document_version_id=versao.id)
        except IntegrityError as exc:
            # Corrida de checksum: dois uploads simultaneos do mesmo arquivo passam
            # pela verificacao previa e so colidem aqui, na constraint UNIQUE.
            await self._remover_orfao(chave)
            raise DuplicateDocumentError from exc
        except Exception:
            await self._remover_orfao(chave)
            raise

        # O id precisa ser lido agora: apos a excecao a sessao pode estar inutilizavel.
        return versao, job.id

    async def _remover_orfao(self, chave: str) -> None:
        """Best-effort: um objeto orfao e inofensivo, mas nao ha razao para deixa-lo."""
        try:
            await self._storage.delete(chave)
        except StorageError:
            logger.warning("orphan_object_cleanup_failed", storage_key=chave)


class UploadFailedError(AppError):
    status_code = 502
    code = ErrorCode.UPSTREAM_UNAVAILABLE
    message = "Nao foi possivel armazenar o arquivo. Tente novamente."
