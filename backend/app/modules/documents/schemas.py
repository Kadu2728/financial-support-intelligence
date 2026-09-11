from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.documents.models import Document, DocumentStatus, DocumentVersion


class DocumentVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    status: DocumentStatus
    is_current: bool
    original_filename: str
    mime_type: str
    file_size_bytes: int
    page_count: int | None
    chunk_count: int | None
    error_code: str | None
    error_detail: str | None
    processed_at: datetime | None
    created_at: datetime

    # `storage_key` e `checksum_sha256` ficam de fora de proposito: sao detalhes de
    # infraestrutura e a chave revela a organizacao interna do bucket.


class DocumentSummary(BaseModel):
    """Documento na listagem.

    Traz o estado da versao mais recente achatado, porque e o que a tabela mostra —
    e evita que o cliente precise percorrer o array de versoes para montar a coluna
    de status.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    category: str | None
    created_at: datetime
    updated_at: datetime

    status: DocumentStatus
    version_count: int
    current_version: int | None
    chunk_count: int | None

    @classmethod
    def from_document(cls, documento: Document) -> DocumentSummary:
        versoes = sorted(documento.versions, key=lambda v: v.version_number)
        ultima = versoes[-1] if versoes else None
        corrente = next((v for v in versoes if v.is_current), None)

        return cls(
            id=documento.id,
            title=documento.title,
            description=documento.description,
            category=documento.category,
            created_at=documento.created_at,
            updated_at=documento.updated_at,
            # O status exibido e o da ULTIMA versao, nao o da corrente: e ele que
            # responde "o que esta acontecendo com este documento agora".
            status=ultima.status if ultima else DocumentStatus.PENDING,
            version_count=len(versoes),
            current_version=corrente.version_number if corrente else None,
            chunk_count=corrente.chunk_count if corrente else None,
        )


class DocumentDetail(DocumentSummary):
    versions: list[DocumentVersionSummary]

    @classmethod
    def from_document(cls, documento: Document) -> DocumentDetail:
        base = DocumentSummary.from_document(documento)
        return cls(
            **base.model_dump(),
            versions=[
                DocumentVersionSummary.model_validate(v)
                for v in sorted(documento.versions, key=lambda v: v.version_number, reverse=True)
            ],
        )


class DocumentPage(BaseModel):
    itens: list[DocumentSummary]
    total: int
    pagina: int
    tamanho: int

    @property
    def paginas(self) -> int:
        return (self.total + self.tamanho - 1) // self.tamanho if self.tamanho else 0


class UploadAccepted(BaseModel):
    """Resposta 202 do upload.

    O processamento e assincrono (ADR-0004), entao o retorno nao pode ser o documento
    pronto: seria mentira. O cliente recebe os ids e acompanha o estado por polling.
    """

    document_id: uuid.UUID
    version_id: uuid.UUID
    version_number: int
    status: DocumentStatus

    @classmethod
    def from_version(cls, versao: DocumentVersion) -> UploadAccepted:
        return cls(
            document_id=versao.document_id,
            version_id=versao.id,
            version_number=versao.version_number,
            status=versao.status,
        )


class ReprocessAccepted(BaseModel):
    document_id: uuid.UUID
    job_id: uuid.UUID
