import type { Metadata } from "next";

import { DocumentsTable } from "@/features/documents/documents-table";
import { UploadDialog } from "@/features/documents/upload-dialog";
import type { DocumentPage } from "@/features/documents/types";
import { ApiError } from "@/lib/bff";
import { authenticatedFetch, getCurrentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Documentos" };
export const dynamic = "force-dynamic";

const TAMANHO = 20;

export default async function DocumentsPage({
  searchParams,
}: PageProps<"/documents">) {
  const params = await searchParams;
  const pagina = Number(params.pagina) || 1;
  const termo = typeof params.q === "string" ? params.q : "";

  const user = await getCurrentUser();
  const podeAdministrar = user?.role === "ADMIN";

  const consulta = new URLSearchParams({ pagina: String(pagina), tamanho: String(TAMANHO) });
  if (termo) consulta.set("q", termo);

  let dados: DocumentPage | null = null;
  let erro: string | null = null;

  try {
    dados = await authenticatedFetch<DocumentPage>(`/api/v1/documents?${consulta}`);
  } catch (error) {
    // A tela precisa dizer o que aconteceu. Uma lista vazia por falha de rede e
    // indistinguivel de um acervo vazio, e as duas pedem acoes opostas.
    erro =
      error instanceof ApiError
        ? error.message
        : "Nao foi possivel carregar o acervo.";
  }

  const total = dados?.total ?? 0;
  const ultimaPagina = Math.max(1, Math.ceil(total / TAMANHO));

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Documentos</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {erro
              ? "Acervo indisponivel no momento."
              : `${total} ${total === 1 ? "documento" : "documentos"} no acervo.`}
          </p>
        </div>

        {podeAdministrar ? <UploadDialog /> : null}
      </header>

      {/* Busca por GET: a consulta fica na URL, entao o resultado e compartilhavel
          e sobrevive a um recarregamento. */}
      <form method="get" className="flex gap-2">
        <input
          type="search"
          name="q"
          defaultValue={termo}
          placeholder="Buscar por titulo"
          aria-label="Buscar documentos por titulo"
          className="h-9 w-full max-w-xs rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button
          type="submit"
          className="h-9 rounded-md border border-input px-3 text-sm font-medium hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Buscar
        </button>
        {termo ? (
          <a
            href="/documents"
            className="flex h-9 items-center rounded-md px-3 text-sm text-muted-foreground hover:text-foreground"
          >
            Limpar
          </a>
        ) : null}
      </form>

      {erro ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3">
          <p className="text-sm font-medium text-destructive">{erro}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Recarregue a pagina. Se o problema continuar, verifique se o servidor esta
            disponivel.
          </p>
        </div>
      ) : (
        <DocumentsTable
          documentos={dados?.itens ?? []}
          podeAdministrar={podeAdministrar}
        />
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
              <a
                href={`/documents?pagina=${pagina - 1}${termo ? `&q=${encodeURIComponent(termo)}` : ""}`}
                className="rounded-md border border-input px-3 py-1.5 hover:bg-accent"
              >
                Anterior
              </a>
            ) : null}
            {pagina < ultimaPagina ? (
              <a
                href={`/documents?pagina=${pagina + 1}${termo ? `&q=${encodeURIComponent(termo)}` : ""}`}
                className="rounded-md border border-input px-3 py-1.5 hover:bg-accent"
              >
                Proxima
              </a>
            ) : null}
          </div>
        </nav>
      ) : null}
    </div>
  );
}
