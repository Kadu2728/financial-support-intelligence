/** Espelha `app/modules/documents/schemas.py`. Se um mudar, o outro quebra. */

export type DocumentStatus = "PENDING" | "PROCESSING" | "READY" | "FAILED" | "SUPERSEDED";

export interface DocumentSummary {
  id: string;
  title: string;
  description: string | null;
  category: string | null;
  created_at: string;
  updated_at: string;
  status: DocumentStatus;
  version_count: number;
  current_version: number | null;
  chunk_count: number | null;
}

export interface DocumentPage {
  itens: DocumentSummary[];
  total: number;
  pagina: number;
  tamanho: number;
}

/**
 * Rotulos e cores por estado.
 *
 * A cor vem de um token semantico (`--status-*`), nao de um nome de cor: trocar a
 * paleta nao pode exigir reescrever este mapa.
 */
export const ESTADO: Record<
  DocumentStatus,
  { rotulo: string; cor: string; descricao: string }
> = {
  PENDING: {
    rotulo: "Na fila",
    cor: "bg-status-pending",
    descricao: "Aguardando processamento",
  },
  PROCESSING: {
    rotulo: "Processando",
    cor: "bg-status-processing",
    descricao: "Extraindo e indexando o conteudo",
  },
  READY: {
    rotulo: "Disponivel",
    cor: "bg-status-ready",
    descricao: "Indexado e disponivel para consulta",
  },
  FAILED: {
    rotulo: "Falhou",
    cor: "bg-status-failed",
    descricao: "O processamento nao foi concluido",
  },
  SUPERSEDED: {
    rotulo: "Substituido",
    cor: "bg-status-pending",
    descricao: "Uma versao mais recente esta em uso",
  },
};

export function formatarTamanho(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatarData(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
