from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import SessionDep, SettingsDep
from app.integrations.storage.base import StorageBackend
from app.integrations.storage.factory import build_storage
from app.modules.auth.dependencies import CurrentUser, RequireAdmin
from app.modules.documents.models import DocumentStatus
from app.modules.documents.repository import (
    DocumentFilters,
    DocumentRepository,
    DocumentVersionRepository,
)
from app.modules.documents.schemas import (
    DocumentDetail,
    DocumentPage,
    DocumentSummary,
    ReprocessAccepted,
    UploadAccepted,
)
from app.modules.documents.service import DocumentService
from app.modules.ingestion.repository import ProcessingJobRepository

router = APIRouter(prefix="/documents", tags=["documents"])


def get_storage(settings: SettingsDep, request: Request) -> StorageBackend:
    """Backend de armazenamento conforme a configuracao (ADR-0007)."""
    return build_storage(settings, request.app.state.session_factory)


def get_document_service(
    session: SessionDep, storage: Annotated[StorageBackend, Depends(get_storage)]
) -> DocumentService:
    return DocumentService(
        documents=DocumentRepository(session),
        versions=DocumentVersionRepository(session),
        jobs=ProcessingJobRepository(session),
        storage=storage,
    )


ServiceDep = Annotated[DocumentService, Depends(get_document_service)]


@router.get("", response_model=DocumentPage, summary="Lista documentos")
async def list_documents(
    service: ServiceDep,
    user: CurrentUser,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filtro: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    categoria: Annotated[str | None, Query(alias="category", max_length=128)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> DocumentPage:
    """Leitura e aberta a qualquer autenticado.

    Um analista precisa saber o que existe no acervo para confiar numa resposta que
    diz nao ter encontrado nada. Administrar o acervo, esse sim, e restrito a ADMIN.
    """
    resultado = await service.list_documents(
        filtros=DocumentFilters(status=status_filtro, category=categoria, termo=q),
        pagina=pagina,
        tamanho=tamanho,
    )
    return DocumentPage(
        itens=[DocumentSummary.from_document(d) for d in resultado.itens],
        total=resultado.total,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.get("/{document_id}", response_model=DocumentDetail, summary="Detalha um documento")
async def get_document(
    document_id: uuid.UUID, service: ServiceDep, user: CurrentUser
) -> DocumentDetail:
    return DocumentDetail.from_document(await service.get_document(document_id))


@router.post(
    "",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Envia um documento",
    responses={
        403: {"description": "Requer papel ADMIN"},
        409: {"description": "Arquivo ja enviado"},
        413: {"description": "Arquivo acima do limite"},
        415: {"description": "Formato nao suportado"},
    },
)
async def upload_document(
    admin: RequireAdmin,
    service: ServiceDep,
    file: Annotated[UploadFile, File()],
    # As restricoes ficam AQUI, na assinatura, e nao num modelo construido dentro do
    # corpo da funcao. Instanciar um BaseModel manualmente levanta `ValidationError`,
    # que nao e o `RequestValidationError` do FastAPI: cai no handler generico e vira
    # 500 em vez de 422. Declaradas assim, o FastAPI valida antes de entrar no endpoint
    # e ainda as publica no OpenAPI.
    title: Annotated[str, Form(min_length=3, max_length=512)],
    description: Annotated[str | None, Form(max_length=2000)] = None,
    category: Annotated[str | None, Form(max_length=128)] = None,
) -> UploadAccepted:
    """202, nao 201: o documento foi aceito, nao esta pronto.

    Extrair e embeddar leva minutos e acontece fora do request (ADR-0004). Responder
    201 afirmaria que o recurso esta disponivel, e uma busca logo em seguida nao o
    encontraria.
    """
    _, versao = await service.create_document(
        title=title.strip(),
        description=_normalizar(description),
        category=_normalizar(category),
        filename=file.filename or "documento",
        stream=file.file,
        uploaded_by=admin.id,
    )
    return UploadAccepted.from_version(versao)


def _normalizar(valor: str | None) -> str | None:
    """Campo de formulario vazio chega como string vazia, nao como ausente."""
    if valor is None:
        return None
    return valor.strip() or None


@router.post(
    "/{document_id}/versions",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Envia uma nova versao",
)
async def upload_version(
    document_id: uuid.UUID,
    admin: RequireAdmin,
    service: ServiceDep,
    file: Annotated[UploadFile, File()],
) -> UploadAccepted:
    versao = await service.add_version(
        document_id=document_id,
        filename=file.filename or "documento",
        stream=file.file,
    )
    return UploadAccepted.from_version(versao)


@router.post(
    "/{document_id}/reprocess",
    response_model=ReprocessAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reenfileira a ultima versao",
)
async def reprocess_document(
    document_id: uuid.UUID, admin: RequireAdmin, service: ServiceDep
) -> ReprocessAccepted:
    job_id = await service.reprocess(document_id)
    return ReprocessAccepted(document_id=document_id, job_id=job_id)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Exclui um documento",
)
async def delete_document(
    document_id: uuid.UUID, admin: RequireAdmin, service: ServiceDep
) -> Response:
    await service.delete_document(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}/content", summary="Baixa o arquivo original")
async def download_document(
    document_id: uuid.UUID, service: ServiceDep, user: CurrentUser
) -> StreamingResponse:
    """Serve o arquivo pelo backend, nao por URL direta do bucket.

    Uma URL publica do storage seria acessivel a quem tivesse o link, sem passar por
    autenticacao — e o acervo e interno. O custo e o trafego passar pela aplicacao;
    URLs assinadas de curta duracao resolveriam isso quando o volume justificar.
    """
    conteudo, versao = await service.get_content(document_id)

    # `filename*` com RFC 5987: nomes com acento quebram o `filename` simples, e
    # documentos em portugues os tem quase sempre.
    nome = quote(versao.original_filename)

    return StreamingResponse(
        iter([conteudo]),
        media_type=versao.mime_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{nome}",
            "Content-Length": str(len(conteudo)),
            # O conteudo de uma versao nunca muda: novas versoes tem id proprio.
            "Cache-Control": "private, max-age=3600",
        },
    )
