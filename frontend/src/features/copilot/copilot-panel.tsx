"use client";

import { SendHorizontal } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { AnswerCard } from "@/features/copilot/answer-card";
import { MENSAGENS_COPILOT, type QueryDetail } from "@/features/copilot/types";

const PADRAO = "Nao foi possivel obter a resposta. Tente novamente.";

const SUGESTOES = [
  "Qual o prazo para contestar uma compra no cartao de credito?",
  "O que significa o codigo COD-2041?",
  "Alguem mandou um Pix para a pessoa errada. Como proceder?",
];

/**
 * Tela principal do analista.
 *
 * Uma pergunta por vez, de proposito: nao e chat. Cada resposta e uma consulta
 * registrada, com fontes e avaliacao — o historico existe em /history. Manter
 * "conversa" exigiria carregar o contexto anterior no prompt, e a rastreabilidade
 * de "qual documento fundamentou esta resposta" ficaria ambigua.
 */
export function CopilotPanel({ gemini_configured }: { gemini_configured: boolean }) {
  const [pergunta, setPergunta] = useState("");
  const [consultando, setConsultando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resposta, setResposta] = useState<QueryDetail | null>(null);

  async function perguntar(texto: string) {
    const limpa = texto.trim();
    if (limpa.length < 3 || consultando) return;

    setConsultando(true);
    setErro(null);

    try {
      const res = await fetch("/api/backend/copilot/query", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: limpa }),
      });
      if (!res.ok) {
        const corpo = await res.json().catch(() => null);
        const codigo = corpo?.error?.code as string | undefined;
        const mensagem = corpo?.error?.message as string | undefined;
        setErro(
          (codigo && MENSAGENS_COPILOT[codigo]) ||
            (res.status === 503 && mensagem ? mensagem : PADRAO),
        );
        return;
      }
      setResposta((await res.json()) as QueryDetail);
    } catch {
      setErro(MENSAGENS_COPILOT.BACKEND_UNREACHABLE ?? PADRAO);
    } finally {
      setConsultando(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void perguntar(pergunta);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter envia; Shift+Enter quebra linha — a convencao que analistas ja conhecem.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void perguntar(pergunta);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {!gemini_configured ? (
        <div className="rounded-lg border border-status-warning/40 bg-status-warning/5 px-4 py-3 text-sm">
          <p className="font-medium">O servico de IA nao esta configurado.</p>
          <p className="mt-1 text-muted-foreground">
            O administrador precisa definir <code className="font-mono text-xs">GEMINI_API_KEY</code>{" "}
            no servidor. Ate la, a busca direta pelo acervo continua disponivel.
          </p>
        </div>
      ) : null}

      <form onSubmit={onSubmit} className="space-y-2">
        <label htmlFor="pergunta" className="text-sm font-medium">
          Pergunte ao acervo
        </label>
        <div className="flex items-end gap-2 rounded-lg border border-input bg-background p-2 focus-within:ring-2 focus-within:ring-ring">
          <textarea
            id="pergunta"
            value={pergunta}
            onChange={(e) => setPergunta(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            maxLength={1000}
            disabled={consultando}
            placeholder="Ex.: Qual o prazo para responder uma queixa de cobranca indevida?"
            className="min-h-[3.25rem] flex-1 resize-none bg-transparent px-1 py-1 text-sm focus-visible:outline-none disabled:opacity-60"
          />
          <Button
            type="submit"
            size="icon"
            disabled={consultando || pergunta.trim().length < 3}
            aria-label="Enviar pergunta"
          >
            <SendHorizontal aria-hidden />
          </Button>
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Enter envia · Shift+Enter quebra linha</span>
          <span className="font-mono tabular-nums">{pergunta.length}/1000</span>
        </div>
      </form>

      {erro ? (
        <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm">
          <p className="font-medium text-destructive">{erro}</p>
        </div>
      ) : null}

      {consultando ? (
        <div aria-live="polite" className="space-y-3 rounded-lg border border-border px-4 py-4">
          <p className="text-sm text-muted-foreground">Buscando no acervo e redigindo a resposta…</p>
          <div className="space-y-2">
            <div className="h-3 w-11/12 animate-pulse rounded bg-muted" />
            <div className="h-3 w-4/5 animate-pulse rounded bg-muted" />
            <div className="h-3 w-3/5 animate-pulse rounded bg-muted" />
          </div>
        </div>
      ) : null}

      {resposta && !consultando ? (
        <AnswerCard key={resposta.id} consulta={resposta} />
      ) : null}

      {!resposta && !consultando && !erro ? (
        <section aria-label="Sugestoes" className="space-y-2">
          <p className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
            Experimente
          </p>
          <ul className="grid gap-2 sm:grid-cols-3">
            {SUGESTOES.map((sugestao) => (
              <li key={sugestao}>
                <button
                  type="button"
                  onClick={() => {
                    setPergunta(sugestao);
                    void perguntar(sugestao);
                  }}
                  disabled={!gemini_configured}
                  className="h-full w-full rounded-md border border-border px-3 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {sugestao}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
