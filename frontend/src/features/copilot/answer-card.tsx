"use client";

import { ExternalLink, ThumbsDown, ThumbsUp } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { AnswerText } from "@/features/copilot/answer-text";
import {
  type Citation,
  type Feedback,
  type FeedbackReason,
  MOTIVOS,
  type QueryDetail,
  STATUS_CONSULTA,
  formatarConfianca,
  formatarMs,
} from "@/features/copilot/types";
import { cn } from "@/lib/utils";

/**
 * Uma consulta respondida: pergunta, resposta com citacoes, fontes e feedback.
 *
 * Usado tanto pelo copilot (resposta recem-gerada) quanto pelo historico — a forma
 * da resposta e a mesma nos dois endpoints, entao o componente tambem e.
 *
 * A confianca exibida e a calculada pelo sistema (ADR-0008). O rotulo diz "confianca
 * estimada", nunca "precisao": o numero descreve a forca da evidencia, nao garante
 * que a resposta esta certa.
 */
export function AnswerCard({ consulta }: { consulta: QueryDetail }) {
  const [ativa, setAtiva] = useState<string | null>(null);
  const fontesRef = useRef<HTMLDivElement>(null);
  // Estado local inicializado da prop: quem renderiza uma consulta NOVA precisa
  // trocar a `key` (o copilot faz isso com `key={resposta.id}`), o que remonta o
  // componente em vez de sincronizar por efeito.
  const [feedback, setFeedback] = useState<Feedback | null>(consulta.feedback);

  function irParaFonte(id: string) {
    setAtiva(id);
    const alvo = fontesRef.current?.querySelector<HTMLElement>(`[data-citacao="${id}"]`);
    alvo?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  const estado = STATUS_CONSULTA[consulta.status];
  const conhecidas = new Set(consulta.citations.map((c) => c.id));

  return (
    <article className="space-y-5">
      <header className="space-y-2">
        <p className="text-sm text-muted-foreground">Pergunta</p>
        <p className="text-base font-medium leading-snug">{consulta.question}</p>
      </header>

      <section
        className={cn(
          "rounded-lg border px-4 py-4",
          consulta.status === "SUCCESS" ? "border-border" : "border-status-warning/40 bg-status-warning/5",
        )}
        aria-labelledby={`resposta-${consulta.id}`}
      >
        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5" title={estado.descricao}>
            <span aria-hidden className={cn("size-1.5 rounded-full", estado.cor)} />
            <span id={`resposta-${consulta.id}`} className="font-medium text-foreground">
              {estado.rotulo}
            </span>
          </span>
          {consulta.status === "SUCCESS" ? (
            <span title="Calculada a partir da forca da evidencia recuperada e das citacoes validas. Nao e a auto-avaliacao do modelo.">
              Confianca estimada{" "}
              <span className="font-mono tabular-nums text-foreground">
                {formatarConfianca(consulta.confidence)}
              </span>
            </span>
          ) : null}
          <span>
            {consulta.citations.length}{" "}
            {consulta.citations.length === 1 ? "fonte" : "fontes"}
          </span>
          <span className="font-mono tabular-nums">{formatarMs(consulta.total_ms)}</span>
        </div>

        {consulta.answer ? (
          <AnswerText
            texto={consulta.answer}
            citacoesConhecidas={conhecidas}
            ativa={ativa}
            onCitar={irParaFonte}
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            Esta consulta falhou antes de produzir uma resposta
            {consulta.error_code ? ` (${consulta.error_code})` : ""}.
          </p>
        )}

        {consulta.status === "INSUFFICIENT_EVIDENCE" ? (
          <p className="mt-3 text-xs text-muted-foreground">
            Esta pergunta foi registrada como lacuna do acervo. Se o tema deveria estar
            coberto, avise quem administra os documentos.
          </p>
        ) : null}
      </section>

      {consulta.citations.length > 0 ? (
        <section ref={fontesRef} aria-label="Fontes" className="space-y-2">
          <h3 className="text-sm font-medium">Fontes</h3>
          <ol className="space-y-2">
            {consulta.citations.map((citacao) => (
              <CitationItem
                key={citacao.id}
                citacao={citacao}
                ativa={ativa === citacao.id}
                onSelecionar={() => setAtiva(ativa === citacao.id ? null : citacao.id)}
              />
            ))}
          </ol>
        </section>
      ) : null}

      {consulta.status !== "FAILED" ? (
        <FeedbackBar queryId={consulta.id} atual={feedback} onSalvo={setFeedback} />
      ) : null}
    </article>
  );
}

function CitationItem({
  citacao,
  ativa,
  onSelecionar,
}: {
  citacao: Citation;
  ativa: boolean;
  onSelecionar: () => void;
}) {
  return (
    <li
      data-citacao={citacao.id}
      className={cn(
        "rounded-md border transition-colors",
        ativa ? "border-primary/60 bg-accent/40" : "border-border",
      )}
    >
      <button
        type="button"
        onClick={onSelecionar}
        aria-expanded={ativa}
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="mt-0.5 inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded bg-accent px-1 font-mono text-[0.6875rem] font-medium">
          {citacao.id}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium leading-snug">{citacao.document_title}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {citacao.section_path ?? "Sem secao identificada"}
            {citacao.page_number !== null ? ` · p. ${citacao.page_number}` : ""}
            {citacao.version_number !== null ? ` · v${citacao.version_number}` : ""}
          </span>
        </span>
      </button>

      {ativa ? (
        <div className="border-t border-border px-3 py-3">
          <blockquote className="max-h-64 overflow-y-auto whitespace-pre-wrap border-l-2 border-primary/40 pl-3 text-sm leading-relaxed text-foreground/90">
            {citacao.excerpt}
          </blockquote>
          <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
            <span className="font-mono tabular-nums">
              similaridade {citacao.score.toFixed(2)}
            </span>
            <a
              href={`/api/backend/documents/${citacao.document_id}/content`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 hover:text-foreground"
            >
              Abrir documento <ExternalLink aria-hidden className="size-3" />
            </a>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function FeedbackBar({
  queryId,
  atual,
  onSalvo,
}: {
  queryId: string;
  atual: Feedback | null;
  onSalvo: (f: Feedback) => void;
}) {
  const [abrindoMotivo, setAbrindoMotivo] = useState(false);
  const [motivo, setMotivo] = useState<FeedbackReason>("INCORRECT");
  const [comentario, setComentario] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function enviar(rating: "POSITIVE" | "NEGATIVE") {
    setSalvando(true);
    setErro(null);
    try {
      const resposta = await fetch(`/api/backend/queries/${queryId}/feedback`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          rating,
          reason: rating === "NEGATIVE" ? motivo : null,
          comment: rating === "NEGATIVE" && comentario.trim() ? comentario.trim() : null,
        }),
      });
      if (!resposta.ok) {
        setErro("Nao foi possivel registrar a avaliacao.");
        return;
      }
      onSalvo((await resposta.json()) as Feedback);
      setAbrindoMotivo(false);
    } catch {
      setErro("Falha de conexao ao registrar a avaliacao.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <section aria-label="Avaliar resposta" className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground">Esta resposta ajudou?</span>
        <Button
          variant={atual?.rating === "POSITIVE" ? "default" : "outline"}
          size="sm"
          disabled={salvando}
          onClick={() => enviar("POSITIVE")}
          aria-pressed={atual?.rating === "POSITIVE"}
        >
          <ThumbsUp aria-hidden /> Sim
        </Button>
        <Button
          variant={atual?.rating === "NEGATIVE" ? "default" : "outline"}
          size="sm"
          disabled={salvando}
          onClick={() => setAbrindoMotivo((v) => !v)}
          aria-pressed={atual?.rating === "NEGATIVE"}
          aria-expanded={abrindoMotivo}
        >
          <ThumbsDown aria-hidden /> Nao
        </Button>
        {atual ? (
          <span className="text-xs text-muted-foreground">
            Avaliacao registrada{atual.reason ? `: ${MOTIVOS[atual.reason]}` : ""}.
          </span>
        ) : null}
      </div>

      {abrindoMotivo ? (
        <form
          className="flex flex-wrap items-end gap-2 rounded-md border border-border p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void enviar("NEGATIVE");
          }}
        >
          <label className="flex flex-col gap-1 text-xs">
            O que deu errado?
            <select
              value={motivo}
              onChange={(e) => setMotivo(e.target.value as FeedbackReason)}
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
            >
              {(Object.keys(MOTIVOS) as FeedbackReason[]).map((chave) => (
                <option key={chave} value={chave}>
                  {MOTIVOS[chave]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs">
            Comentario (opcional)
            <input
              value={comentario}
              onChange={(e) => setComentario(e.target.value)}
              maxLength={1000}
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
            />
          </label>
          <Button type="submit" size="sm" disabled={salvando}>
            Registrar
          </Button>
        </form>
      ) : null}
      {erro ? <p className="text-xs text-destructive">{erro}</p> : null}
    </section>
  );
}
