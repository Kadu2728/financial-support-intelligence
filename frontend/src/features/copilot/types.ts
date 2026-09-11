/** Espelha `app/modules/queries/schemas.py` e `app/modules/search/schemas.py`. */

export type QueryStatus = "SUCCESS" | "INSUFFICIENT_EVIDENCE" | "FAILED";
export type FeedbackRating = "POSITIVE" | "NEGATIVE";
export type FeedbackReason = "INCORRECT" | "INCOMPLETE" | "WRONG_SOURCE" | "OUTDATED" | "OTHER";

export interface Citation {
  id: string; // "C1", "C2"... — o marcador que aparece no texto
  rank: number;
  chunk_id: string;
  document_id: string;
  document_title: string;
  version_id: string;
  version_number: number | null;
  section_path: string | null;
  section_label: string | null;
  page_number: number | null;
  excerpt: string;
  char_start: number;
  char_end: number;
  score: number;
}

export interface Feedback {
  rating: FeedbackRating;
  reason: FeedbackReason | null;
  comment: string | null;
  created_at: string;
}

export interface QueryDetail {
  id: string;
  question: string;
  status: QueryStatus;
  answer: string | null;
  insufficient_evidence: boolean;
  citations: Citation[];
  confidence: number | null;
  chunks_retrieved: number;
  top_score: number | null;
  retrieval_ms: number | null;
  generation_ms: number | null;
  total_ms: number | null;
  model: string | null;
  error_code: string | null;
  created_at: string;
  feedback: Feedback | null;
}

export interface QuerySummary {
  id: string;
  question: string;
  status: QueryStatus;
  answer_preview: string | null;
  confidence: number | null;
  total_ms: number | null;
  created_at: string;
  feedback_rating: FeedbackRating | null;
}

export interface QueryPage {
  itens: QuerySummary[];
  total: number;
  pagina: number;
  tamanho: number;
}

export type SearchMode = "semantic" | "lexical" | "hybrid";

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  document_title: string;
  version_id: string;
  section_path: string | null;
  section_label: string | null;
  page_number: number | null;
  content: string;
  char_start: number;
  char_end: number;
  score: number;
  similarity: number | null;
  semantic_rank: number | null;
  lexical_rank: number | null;
}

export interface SearchResponse {
  mode: SearchMode;
  hits: SearchHit[];
  retrieval_ms: number;
  top_similarity: number | null;
}

export const MOTIVOS: Record<FeedbackReason, string> = {
  INCORRECT: "Resposta incorreta",
  INCOMPLETE: "Resposta incompleta",
  WRONG_SOURCE: "Fonte errada",
  OUTDATED: "Informacao desatualizada",
  OTHER: "Outro motivo",
};

export const STATUS_CONSULTA: Record<
  QueryStatus,
  { rotulo: string; cor: string; descricao: string }
> = {
  SUCCESS: {
    rotulo: "Respondida",
    cor: "bg-status-ready",
    descricao: "Resposta fundamentada em documentos do acervo",
  },
  INSUFFICIENT_EVIDENCE: {
    rotulo: "Sem evidencia",
    cor: "bg-status-warning",
    descricao: "O acervo nao tem base suficiente para responder",
  },
  FAILED: {
    rotulo: "Falhou",
    cor: "bg-status-failed",
    descricao: "Erro tecnico ao gerar a resposta",
  },
};

/**
 * Mensagens por `code` do backend — o contrato estavel. Cada uma diz o que houve e o
 * que fazer; "erro 503" sozinho nao orienta ninguem.
 */
export const MENSAGENS_COPILOT: Record<string, string> = {
  UPSTREAM_UNAVAILABLE:
    "O servico de IA esta indisponivel. Se o problema persistir, avise o administrador.",
  GENERATION_TIMEOUT: "O modelo demorou demais para responder. Tente reformular a pergunta.",
  GENERATION_FAILED: "O modelo devolveu uma resposta invalida. Tente novamente.",
  RATE_LIMITED: "Muitas perguntas em pouco tempo. Aguarde alguns segundos.",
  VALIDATION_ERROR: "A pergunta precisa ter entre 3 e 1000 caracteres.",
  TOKEN_INVALID: "Sua sessao expirou. Faca login novamente.",
  BACKEND_UNREACHABLE: "Nao foi possivel falar com o servidor. Verifique a conexao.",
};

export function formatarConfianca(valor: number | null): string {
  if (valor === null) return "—";
  return `${Math.round(valor * 100)}%`;
}

export function formatarMs(valor: number | null): string {
  if (valor === null) return "—";
  return valor >= 1000 ? `${(valor / 1000).toFixed(1)} s` : `${valor} ms`;
}
