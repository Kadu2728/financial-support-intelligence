from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.dependencies import SessionDep
from app.modules.auth.dependencies import RequireAdmin
from app.modules.intelligence.repository import IntelligenceRepository
from app.modules.intelligence.service import IntelligenceService, VisaoGeral

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


class TotaisOut(BaseModel):
    consultas: int
    sucesso: int
    sem_evidencia: int
    falhas: int


class LatenciaOut(BaseModel):
    p50_ms: int | None
    p95_ms: int | None
    media_ms: int | None
    retrieval_medio_ms: int | None
    generation_medio_ms: int | None


class MotivoOut(BaseModel):
    reason: str
    count: int


class FeedbackResumoOut(BaseModel):
    total: int
    positivos: int
    negativos: int
    taxa_positiva: float | None
    motivos: list[MotivoOut]


class DiaOut(BaseModel):
    dia: date
    consultas: int
    sem_evidencia: int


class DocumentoCitadoOut(BaseModel):
    document_id: uuid.UUID
    title: str
    citacoes: int
    consultas: int


class SecaoCitadaOut(BaseModel):
    document_id: uuid.UUID
    document_title: str
    section_path: str | None
    citacoes: int


class LacunaOut(BaseModel):
    representante: str
    ocorrencias: int
    exemplos: list[str]
    ultima_em: datetime
    query_ids: list[str]


class OverviewOut(BaseModel):
    dias: int
    desde: datetime
    ate: datetime
    amostra_minima: int
    amostra_suficiente: bool
    totais: TotaisOut
    taxa_sucesso: float | None
    taxa_sem_evidencia: float | None
    taxa_falha: float | None
    latencia: LatenciaOut
    confianca_media: float | None
    feedback: FeedbackResumoOut
    serie_diaria: list[DiaOut]
    documentos_mais_citados: list[DocumentoCitadoOut]
    secoes_mais_citadas: list[SecaoCitadaOut]
    lacunas: list[LacunaOut]
    documentos_ativos: int
    chunks_indexados: int

    @classmethod
    def from_visao(cls, v: VisaoGeral) -> OverviewOut:
        return cls(
            dias=v.dias,
            desde=v.desde,
            ate=v.ate,
            amostra_minima=v.amostra_minima,
            amostra_suficiente=v.amostra_suficiente,
            totais=TotaisOut(
                consultas=v.totais.consultas,
                sucesso=v.totais.sucesso,
                sem_evidencia=v.totais.sem_evidencia,
                falhas=v.totais.falhas,
            ),
            taxa_sucesso=v.taxa_sucesso,
            taxa_sem_evidencia=v.taxa_sem_evidencia,
            taxa_falha=v.taxa_falha,
            latencia=LatenciaOut(
                p50_ms=v.latencia.p50_ms,
                p95_ms=v.latencia.p95_ms,
                media_ms=v.latencia.media_ms,
                retrieval_medio_ms=v.latencia.retrieval_medio_ms,
                generation_medio_ms=v.latencia.generation_medio_ms,
            ),
            confianca_media=v.confianca_media,
            feedback=FeedbackResumoOut(
                total=v.feedback.total,
                positivos=v.feedback.positivos,
                negativos=v.feedback.negativos,
                taxa_positiva=v.taxa_feedback_positivo,
                motivos=[MotivoOut(reason=r, count=c) for r, c in v.feedback.motivos],
            ),
            serie_diaria=[
                DiaOut(dia=d.dia, consultas=d.consultas, sem_evidencia=d.sem_evidencia)
                for d in v.serie_diaria
            ],
            documentos_mais_citados=[
                DocumentoCitadoOut(
                    document_id=d.document_id,
                    title=d.title,
                    citacoes=d.citacoes,
                    consultas=d.consultas,
                )
                for d in v.documentos_mais_citados
            ],
            secoes_mais_citadas=[
                SecaoCitadaOut(
                    document_id=s.document_id,
                    document_title=s.document_title,
                    section_path=s.section_path,
                    citacoes=s.citacoes,
                )
                for s in v.secoes_mais_citadas
            ],
            lacunas=[
                LacunaOut(
                    representante=g.representante,
                    ocorrencias=g.ocorrencias,
                    exemplos=g.exemplos,
                    ultima_em=g.ultima_em,
                    query_ids=g.query_ids,
                )
                for g in v.lacunas
            ],
            documentos_ativos=v.documentos_ativos,
            chunks_indexados=v.chunks_indexados,
        )


@router.get(
    "/overview",
    response_model=OverviewOut,
    summary="Visao geral do periodo",
    responses={403: {"description": "Requer papel ADMIN"}},
)
async def overview(
    session: SessionDep,
    user: RequireAdmin,
    dias: Annotated[int, Query(ge=1, le=365)] = 30,
) -> OverviewOut:
    """Metricas agregadas das consultas. So o que foi medido; taxas sobre amostra
    pequena vem nulas (ver `amostra_minima`)."""
    visao = await IntelligenceService(IntelligenceRepository(session)).visao_geral(dias=dias)
    return OverviewOut.from_visao(visao)
