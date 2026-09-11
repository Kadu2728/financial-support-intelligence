"use client";

import { Fragment, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Renderiza o texto da resposta com os marcadores de citacao como chips.
 *
 * Nao usa uma biblioteca de Markdown de proposito: o modelo devolve um subconjunto
 * pequeno (paragrafos, listas, negrito) e uma biblioteca completa traria HTML
 * arbitrario para dentro da tela — e o texto vem de um modelo que le documentos
 * enviados por terceiros. Este renderizador so produz os nos que conhece.
 */

const MARCADOR = /\[(C\d+)\]/g;
const NEGRITO = /\*\*(.+?)\*\*/g;

interface Props {
  texto: string;
  citacoesConhecidas: Set<string>;
  ativa: string | null;
  onCitar: (id: string) => void;
}

export function AnswerText({ texto, citacoesConhecidas, ativa, onCitar }: Props) {
  const blocos = separarBlocos(texto);

  return (
    <div className="space-y-3 text-[0.9375rem] leading-relaxed">
      {blocos.map((bloco, indice) => {
        if (bloco.tipo === "lista") {
          const Tag = bloco.ordenada ? "ol" : "ul";
          return (
            <Tag
              key={indice}
              className={cn(
                "space-y-1.5 pl-5",
                bloco.ordenada ? "list-decimal" : "list-disc",
              )}
            >
              {bloco.itens.map((item, i) => (
                <li key={i} className="pl-1">
                  <Inline texto={item} conhecidas={citacoesConhecidas} ativa={ativa} onCitar={onCitar} />
                </li>
              ))}
            </Tag>
          );
        }
        return (
          <p key={indice}>
            <Inline texto={bloco.texto} conhecidas={citacoesConhecidas} ativa={ativa} onCitar={onCitar} />
          </p>
        );
      })}
    </div>
  );
}

function Inline({
  texto,
  conhecidas,
  ativa,
  onCitar,
}: {
  texto: string;
  conhecidas: Set<string>;
  ativa: string | null;
  onCitar: (id: string) => void;
}) {
  const partes: ReactNode[] = [];
  let ultimo = 0;
  let chave = 0;

  for (const match of texto.matchAll(MARCADOR)) {
    const inicio = match.index ?? 0;
    if (inicio > ultimo) {
      partes.push(<Fragment key={chave++}>{comNegrito(texto.slice(ultimo, inicio))}</Fragment>);
    }
    const id = match[1] ?? "";
    if (conhecidas.has(id)) {
      partes.push(
        <button
          key={chave++}
          type="button"
          onClick={() => onCitar(id)}
          aria-label={`Ver fonte ${id}`}
          className={cn(
            "mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded px-1 align-text-top",
            "font-mono text-[0.6875rem] font-medium transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            ativa === id
              ? "bg-primary text-primary-foreground"
              : "bg-accent text-accent-foreground hover:bg-primary/15",
          )}
        >
          {id}
        </button>,
      );
    }
    ultimo = inicio + match[0].length;
  }
  if (ultimo < texto.length) {
    partes.push(<Fragment key={chave++}>{comNegrito(texto.slice(ultimo))}</Fragment>);
  }
  return <>{partes}</>;
}

function comNegrito(texto: string): ReactNode[] {
  const saida: ReactNode[] = [];
  let ultimo = 0;
  let chave = 0;
  for (const match of texto.matchAll(NEGRITO)) {
    const inicio = match.index ?? 0;
    if (inicio > ultimo) saida.push(texto.slice(ultimo, inicio));
    saida.push(<strong key={chave++}>{match[1] ?? ""}</strong>);
    ultimo = inicio + match[0].length;
  }
  if (ultimo < texto.length) saida.push(texto.slice(ultimo));
  return saida;
}

type Bloco =
  | { tipo: "paragrafo"; texto: string }
  | { tipo: "lista"; ordenada: boolean; itens: string[] };

function separarBlocos(texto: string): Bloco[] {
  const blocos: Bloco[] = [];
  let paragrafo: string[] = [];
  let lista: { ordenada: boolean; itens: string[] } | null = null;

  const fecharParagrafo = () => {
    if (paragrafo.length) {
      blocos.push({ tipo: "paragrafo", texto: paragrafo.join(" ") });
      paragrafo = [];
    }
  };
  const fecharLista = () => {
    if (lista) {
      blocos.push({ tipo: "lista", ...lista });
      lista = null;
    }
  };

  for (const bruta of texto.split("\n")) {
    const linha = bruta.trim();
    if (!linha) {
      fecharParagrafo();
      fecharLista();
      continue;
    }
    const ordenada = /^\d+[.)]\s+/.test(linha);
    const naoOrdenada = /^[-*•]\s+/.test(linha);
    if (ordenada || naoOrdenada) {
      fecharParagrafo();
      const item = linha.replace(/^(\d+[.)]|[-*•])\s+/, "");
      if (!lista || lista.ordenada !== ordenada) {
        fecharLista();
        lista = { ordenada, itens: [] };
      }
      lista.itens.push(item);
      continue;
    }
    if (lista) {
      // Continuacao de item de lista (linha sem marcador logo apos um item).
      lista.itens[lista.itens.length - 1] += ` ${linha}`;
      continue;
    }
    paragrafo.push(linha.replace(/^#{1,6}\s+/, ""));
  }
  fecharParagrafo();
  fecharLista();
  return blocos;
}
