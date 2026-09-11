"use client";

import { ExternalLink } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  MENSAGENS_COPILOT,
  type SearchHit,
  type SearchMode,
  type SearchResponse,
} from "@/features/copilot/types";
import { cn } from "@/lib/utils";

const MODOS: { valor: SearchMode; rotulo: string; descricao: string }[] = [
  { valor: "hybrid", rotulo: "Hibrida", descricao: "Semantica + lexical, fundidas por RRF" },
  { valor: "semantic", rotulo: "Semantica", descricao: "Similaridade de embeddings" },
  { valor: "lexical", rotulo: "Lexical", descricao: "Full-text em portugues" },
];

/**
 * Busca direta, sem geracao.
 *
 * Tambem e a ferramenta de diagnostico do RAG: quando uma resposta do copiloto vem
 * errada, a primeira pergunta e "o retrieval trouxe o trecho certo?". Por isso os
 * ranks de cada perna sao exibidos — sao o que explica por que um trecho subiu.
 */
export function SearchPanel({ gemini_configured }: { gemini_configured: boolean }) {
  const [pergunta, setPergunta] = useState("");
  const [modo, setModo] = useState<SearchMode>(gemini_configured ? "hybrid" : "lexical");
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<SearchResponse | null>(null);
  const [aberto, setAberto] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const limpa = pergunta.trim();
    if (limpa.length < 2) return;

    setBuscando(true);
    setErro(null);
    try {
      const res = await fetch("/api/backend/search", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: limpa, mode: modo, top_k: 10 }),
      });
      if (!res.ok) {
        const corpo = await res.json().catch(() => null);
        const codigo = corpo?.error?.code as string | undefined;
        setErro(
          (codigo && MENSAGENS_COPILOT[codigo]) ||
            (corpo?.error?.message as string | undefined) ||
            "Nao foi possivel buscar.",
        );
        return;
      }
      setResultado((await res.json()) as SearchResponse);
      setAberto(null);
    } catch {
      setErro(MENSAGENS_COPILOT.BACKEND_UNREACHABLE ?? "Falha de conexao.");
    } finally {
      setBuscando(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <form onSubmit={onSubmit} className="space-y-3">
        <div className="flex gap-2">
          <input
            value={pergunta}
            onChange={(e) => setPergunta(e.target.value)}
            maxLength={1000}
            placeholder="Termo, codigo ou pergunta — ex.: FOR-CAD-017"
            aria-label="Termo de busca"
            className="h-9 flex-1 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button type="submit" disabled={buscando || pergunta.trim().length < 2}>
            {buscando ? "Buscando…" : "Buscar"}
          </Button>
        </div>

        <fieldset className="flex flex-wrap items-center gap-1" aria-label="Modo de busca">
          {MODOS.map((item) => {
            const desabilitado = !gemini_configured && item.valor !== "lexical";
            return (
              <label
                key={item.valor}
                title={desabilitado ? "Exige GEMINI_API_KEY configurada" : item.descricao}
                className={cn(
                  "cursor-pointer rounded-md border px-2.5 py-1 text-xs transition-colors",
                  modo === item.valor
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border text-muted-foreground hover:text-foreground",
                  desabilitado && "cursor-not-allowed opacity-50",
                )}
              >
                <input
                  type="radio"
                  name="modo"
                  value={item.valor}
                  checked={modo === item.valor}
                  disabled={desabilitado}
                  onChange={() => setModo(item.valor)}
                  className="sr-only"
                />
                {item.rotulo}
              </label>
            );
          })}
        </fieldset>
      </form>

      {erro ? (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {erro}
        </p>
      ) : null}

      {resultado ? (
        <section aria-label="Resultados" className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {resultado.hits.length} {resultado.hits.length === 1 ? "trecho" : "trechos"} ·
            modo {resultado.mode} ·{" "}
            <span className="font-mono tabular-nums">{resultado.retrieval_ms} ms</span>
            {resultado.top_similarity !== null ? (
              <>
                {" "}· melhor similaridade{" "}
                <span className="font-mono tabular-nums">{resultado.top_similarity.toFixed(3)}</span>
              </>
            ) : null}
          </p>

          {resultado.hits.length === 0 ? (
            <p className="rounded-md border border-border px-4 py-6 text-center text-sm text-muted-foreground">
              Nenhum trecho encontrado. Tente outros termos ou o modo hibrido.
            </p>
          ) : (
            <ol className="space-y-2">
              {resultado.hits.map((hit, indice) => (
                <HitItem
                  key={hit.chunk_id}
                  posicao={indice + 1}
                  hit={hit}
                  aberto={aberto === hit.chunk_id}
                  onToggle={() => setAberto(aberto === hit.chunk_id ? null : hit.chunk_id)}
                />
              ))}
            </ol>
          )}
        </section>
      ) : null}
    </div>
  );
}

function HitItem({
  posicao,
  hit,
  aberto,
  onToggle,
}: {
  posicao: number;
  hit: SearchHit;
  aberto: boolean;
  onToggle: () => void;
}) {
  const previa = hit.content.length > 240 ? `${hit.content.slice(0, 240).trimEnd()}…` : hit.content;

  return (
    <li className={cn("rounded-md border", aberto ? "border-primary/60" : "border-border")}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={aberto}
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="mt-0.5 w-5 shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
          {posicao}
        </span>
        <span className="min-w-0 flex-1 space-y-1">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-sm font-medium">{hit.document_title}</span>
            <span className="truncate text-xs text-muted-foreground">
              {hit.section_path ?? "Sem secao"}
              {hit.page_number !== null ? ` · p. ${hit.page_number}` : ""}
            </span>
          </span>
          {!aberto ? (
            <span className="block text-sm leading-snug text-muted-foreground">{previa}</span>
          ) : null}
          <span className="flex flex-wrap gap-x-3 font-mono text-[0.6875rem] text-muted-foreground tabular-nums">
            {hit.similarity !== null ? <span>cos {hit.similarity.toFixed(3)}</span> : null}
            {hit.semantic_rank !== null ? <span>sem #{hit.semantic_rank}</span> : null}
            {hit.lexical_rank !== null ? <span>lex #{hit.lexical_rank}</span> : null}
            <span>rrf {hit.score.toFixed(4)}</span>
          </span>
        </span>
      </button>
      {aberto ? (
        <div className="border-t border-border px-3 py-3">
          <p className="max-h-80 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed">
            {hit.content}
          </p>
          <a
            href={`/api/backend/documents/${hit.document_id}/content`}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            Abrir documento <ExternalLink aria-hidden className="size-3" />
          </a>
        </div>
      ) : null}
    </li>
  );
}
