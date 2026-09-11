/** Espelha `app/modules/intelligence/router.py`. */

export interface Overview {
  dias: number;
  desde: string;
  ate: string;
  amostra_minima: number;
  amostra_suficiente: boolean;
  totais: { consultas: number; sucesso: number; sem_evidencia: number; falhas: number };
  taxa_sucesso: number | null;
  taxa_sem_evidencia: number | null;
  taxa_falha: number | null;
  latencia: {
    p50_ms: number | null;
    p95_ms: number | null;
    media_ms: number | null;
    retrieval_medio_ms: number | null;
    generation_medio_ms: number | null;
  };
  confianca_media: number | null;
  feedback: {
    total: number;
    positivos: number;
    negativos: number;
    taxa_positiva: number | null;
    motivos: { reason: string; count: number }[];
  };
  serie_diaria: { dia: string; consultas: number; sem_evidencia: number }[];
  documentos_mais_citados: {
    document_id: string;
    title: string;
    citacoes: number;
    consultas: number;
  }[];
  secoes_mais_citadas: {
    document_id: string;
    document_title: string;
    section_path: string | null;
    citacoes: number;
  }[];
  lacunas: {
    representante: string;
    ocorrencias: number;
    exemplos: string[];
    ultima_em: string;
    query_ids: string[];
  }[];
  documentos_ativos: number;
  chunks_indexados: number;
}

export function pct(valor: number | null): string {
  return valor === null ? "—" : `${Math.round(valor * 100)}%`;
}
