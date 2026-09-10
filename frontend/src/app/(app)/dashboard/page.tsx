import type { Metadata } from "next";

import { getCurrentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Painel" };

/**
 * Placeholder honesto da Fase 3.
 *
 * O painel real depende de dados que ainda nao existem: consultas (Fase 8) e as
 * agregacoes do Intelligence (Fase 9). Preencher com numeros inventados agora
 * contrariaria o principio central do produto — todo indicador vem do banco.
 *
 * Entao esta tela mostra o que e verdade hoje: quem esta logado e o que ja funciona.
 */
export default async function DashboardPage() {
  const user = await getCurrentUser();

  const proximasFases = [
    { fase: "4", titulo: "Documentos", descricao: "Upload, versoes e ciclo de processamento" },
    { fase: "5", titulo: "Ingestao", descricao: "Extracao, chunking e embeddings" },
    { fase: "6", titulo: "Busca", descricao: "Vetorial + lexical com fusao RRF" },
    { fase: "7", titulo: "Copiloto", descricao: "Respostas fundamentadas com citacoes" },
  ];

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">
          Bom dia, {user?.full_name.split(" ")[0]}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A base de conhecimento ainda nao foi carregada. O painel passa a exibir
          indicadores reais assim que houver consultas registradas.
        </p>
      </header>

      <section className="rounded-lg border border-border">
        <div className="border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-medium">Em construcao</h2>
        </div>
        <ul className="divide-y divide-border">
          {proximasFases.map(({ fase, titulo, descricao }) => (
            <li key={fase} className="flex items-baseline gap-4 px-4 py-3">
              <span className="font-mono text-xs text-muted-foreground">F{fase}</span>
              <div className="min-w-0">
                <p className="text-sm font-medium">{titulo}</p>
                <p className="text-sm text-muted-foreground">{descricao}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
