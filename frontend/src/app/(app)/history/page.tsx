import type { Metadata } from "next";
import Link from "next/link";

import { STATUS_CONSULTA, formatarConfianca, type QueryPage } from "@/features/copilot/types";
import { formatarData } from "@/features/documents/types";
import { ApiError } from "@/lib/bff";
import { authenticatedFetch, getCurrentUser } from "@/lib/session";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Historico" };
export const dynamic = "force-dynamic";

const TAMANHO = 20;

export default async function HistoryPage({ searchParams }: PageProps<"/history">) {
  const params = await searchParams;
  const pagina = Number(params.pagina) || 1;
  const todos = params.todos === "1";

  const user = await getCurrentUser();
  const admin = user?.role === "ADMIN";

  const consulta = new URLSearchParams({ pagina: String(pagina), tamanho: String(TAMANHO) });
  if (todos && admin) consulta.set("todos", "true");

  let dados: QueryPage | null = null;
  let erro: string | null = null;
  try {
    dados = await authenticatedFetch<QueryPage>(`/api/v1/queries?${consulta}`);
  } catch (error) {
    erro = error instanceof ApiError ? error.message : "Nao foi possivel carregar o historico.";
  }

  const itens = dados?.itens ?? [];
  const total = dados?.total ?? 0;
  const ultimaPagina = Math.max(1, Math.ceil(total / TAMANHO));
  const base = `/history?${todos ? "todos=1&" : ""}`;
  const escopo = todos && admin ? " de todos os usuarios" : "";

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Historico</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {erro
              ? "Historico indisponivel no momento."
              : `${total} ${total === 1 ? "consulta" : "consultas"}${escopo}.`}
          </p>
        </div>
        {admin ? (
          <nav className="flex gap-1 text-xs" aria-label="Escopo">
            <EscopoLink href="/history" ativo={!todos}>
              Minhas
            </EscopoLink>
            <EscopoLink href="/history?todos=1" ativo={todos}>
              Todas
            </EscopoLink>
          </nav>
        ) : null}
      </header>

      {erro ? (
        <p className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {erro}
        </p>
      ) : itens.length === 0 ? (
        <div className="rounded-lg border border-border px-4 py-10 text-center">
          <p className="text-sm font-medium">Nenhuma consulta ainda.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            As perguntas feitas ao{" "}
            <Link href="/copilot" className="underline underline-offset-4">
              copiloto
            </Link>{" "}
            aparecem aqui com resposta e fontes.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {itens.map((item) => {
            const estado = STATUS_CONSULTA[item.status];
            const rodape =
              item.status === "SUCCESS"
                ? `confianca ${formatarConfianca(item.confidence)}`
                : estado.rotulo;
            const avaliacao =
              item.feedback_rating === "POSITIVE"
                ? " · util"
                : item.feedback_rating === "NEGATIVE"
                  ? " · com problema"
                  : "";
            return (
              <li key={item.id}>
                <Link
                  href={`/history/${item.id}`}
                  className="flex items-start gap-4 px-4 py-3 transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="mt-1.5 inline-flex shrink-0 items-center" title={estado.descricao}>
                    <span aria-hidden className={cn("size-1.5 rounded-full", estado.cor)} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{item.question}</span>
                    <span className="block truncate text-sm text-muted-foreground">
                      {item.answer_preview ?? "Sem resposta"}
                    </span>
                  </span>
                  <span className="hidden shrink-0 flex-col items-end gap-0.5 text-right text-xs text-muted-foreground sm:flex">
                    <span>{formatarData(item.created_at)}</span>
                    <span className="font-mono tabular-nums">
                      {rodape}
                      {avaliacao}
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      {ultimaPagina > 1 ? (
        <nav
          aria-label="Paginacao"
          className="flex items-center justify-between text-sm text-muted-foreground"
        >
          <span>
            Pagina {pagina} de {ultimaPagina}
          </span>
          <div className="flex gap-2">
            {pagina > 1 ? (
              <Link
                href={`${base}pagina=${pagina - 1}`}
                className="rounded-md border border-input px-3 py-1.5 hover:bg-accent"
              >
                Anterior
              </Link>
            ) : null}
            {pagina < ultimaPagina ? (
              <Link
                href={`${base}pagina=${pagina + 1}`}
                className="rounded-md border border-input px-3 py-1.5 hover:bg-accent"
              >
                Proxima
              </Link>
            ) : null}
          </div>
        </nav>
      ) : null}
    </div>
  );
}

function EscopoLink({
  href,
  ativo,
  children,
}: {
  href: string;
  ativo: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "rounded-md border px-2.5 py-1",
        ativo
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </Link>
  );
}
