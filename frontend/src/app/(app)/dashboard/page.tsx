import type { Metadata } from "next";
import Link from "next/link";
import { BarChart3, FileText, MessageSquareText, Search } from "lucide-react";

import { STATUS_CONSULTA, type QueryPage } from "@/features/copilot/types";
import { formatarData, type DocumentPage } from "@/features/documents/types";
import { getCapabilities } from "@/lib/capabilities";
import { authenticatedFetch, getCurrentUser } from "@/lib/session";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Painel" };
export const dynamic = "force-dynamic";

/**
 * Painel de entrada.
 *
 * Mostra apenas o que e verdade para ESTE usuario agora: suas ultimas consultas, o
 * tamanho do acervo e se o copiloto esta operacional. Agregacoes de equipe ficam em
 * /intelligence, onde a guarda de amostra minima se aplica.
 */
export default async function DashboardPage() {
  const user = await getCurrentUser();
  const { gemini } = await getCapabilities();

  const [consultas, documentos] = await Promise.all([
    authenticatedFetch<QueryPage>("/api/v1/queries?pagina=1&tamanho=5").catch(() => null),
    authenticatedFetch<DocumentPage>("/api/v1/documents?pagina=1&tamanho=1").catch(() => null),
  ]);

  const saudacao = (() => {
    const hora = new Date().getHours();
    if (hora < 12) return "Bom dia";
    if (hora < 18) return "Boa tarde";
    return "Boa noite";
  })();

  const atalhos = [
    {
      href: "/copilot",
      titulo: "Perguntar ao copiloto",
      descricao: "Resposta com fontes, ou recusa explicita",
      Icone: MessageSquareText,
    },
    {
      href: "/search",
      titulo: "Buscar no acervo",
      descricao: "Trechos exatos, sem redacao",
      Icone: Search,
    },
    {
      href: "/documents",
      titulo: "Documentos",
      descricao:
        documentos === null
          ? "Acervo indisponivel"
          : `${documentos.total} ${documentos.total === 1 ? "documento" : "documentos"}`,
      Icone: FileText,
    },
    ...(user?.role === "ADMIN"
      ? [
          {
            href: "/intelligence",
            titulo: "Inteligencia",
            descricao: "Lacunas, uso e qualidade",
            Icone: BarChart3,
          },
        ]
      : []),
  ];

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">
          {saudacao}, {user?.full_name.split(" ")[0]}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {gemini
            ? "Copiloto operacional. Toda resposta traz a fonte; quando o acervo nao cobre, ele diz."
            : "O copiloto esta desligado: falta configurar a chave do servico de IA no servidor. A busca lexical continua disponivel."}
        </p>
      </header>

      <section aria-label="Atalhos" className="grid gap-3 sm:grid-cols-2">
        {atalhos.map(({ href, titulo, descricao, Icone }) => (
          <Link
            key={href}
            href={href}
            className="flex items-start gap-3 rounded-lg border border-border px-4 py-3 transition-colors hover:border-primary/40 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Icone aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <span>
              <span className="block text-sm font-medium">{titulo}</span>
              <span className="block text-sm text-muted-foreground">{descricao}</span>
            </span>
          </Link>
        ))}
      </section>

      <section className="rounded-lg border border-border">
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-medium">Suas ultimas consultas</h2>
          <Link href="/history" className="text-xs text-muted-foreground hover:text-foreground">
            Ver historico
          </Link>
        </div>
        {consultas === null ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">Historico indisponivel.</p>
        ) : consultas.itens.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            Voce ainda nao fez nenhuma pergunta.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {consultas.itens.map((item) => {
              const estado = STATUS_CONSULTA[item.status];
              return (
                <li key={item.id}>
                  <Link
                    href={`/history/${item.id}`}
                    className="flex items-center gap-3 px-4 py-2.5 hover:bg-accent/50"
                  >
                    <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", estado.cor)} />
                    <span className="min-w-0 flex-1 truncate text-sm">{item.question}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {formatarData(item.created_at)}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
