"use client";

import { FileText, RotateCw, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  formatarData,
  type DocumentSummary,
} from "@/features/documents/types";

/**
 * Tabela do acervo.
 *
 * Densa de proposito: o administrador precisa ver o maximo de documentos sem rolar, e
 * comparar estados entre linhas. Padding pequeno e altura de linha contida servem a
 * isso melhor que cards espacados.
 */
export function DocumentsTable({
  documentos,
  podeAdministrar,
}: {
  documentos: DocumentSummary[];
  podeAdministrar: boolean;
}) {
  const router = useRouter();
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [confirmando, setConfirmando] = useState<string | null>(null);

  async function agir(id: string, acao: "reprocess" | "delete") {
    setOcupado(id);
    try {
      await fetch(
        `/api/backend/documents/${id}${acao === "reprocess" ? "/reprocess" : ""}`,
        { method: acao === "reprocess" ? "POST" : "DELETE" },
      );
      router.refresh();
    } finally {
      setOcupado(null);
      setConfirmando(null);
    }
  }

  if (documentos.length === 0) {
    return (
      <div className="rounded-lg border border-border px-6 py-12 text-center">
        <FileText aria-hidden className="mx-auto size-6 text-muted-foreground" />
        <p className="mt-3 text-sm font-medium">Nenhum documento no acervo</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
          {podeAdministrar
            ? "Envie manuais, procedimentos e politicas para que o Copiloto possa consulta-los."
            : "Um administrador precisa enviar documentos antes que as consultas retornem resultados."}
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[46rem] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <th scope="col" className="px-3 py-2 font-medium">Documento</th>
            <th scope="col" className="px-3 py-2 font-medium">Categoria</th>
            <th scope="col" className="px-3 py-2 font-medium">Estado</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Versoes</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Trechos</th>
            <th scope="col" className="px-3 py-2 font-medium">Atualizado</th>
            {podeAdministrar ? (
              <th scope="col" className="px-3 py-2 text-right font-medium">
                <span className="sr-only">Acoes</span>
              </th>
            ) : null}
          </tr>
        </thead>

        <tbody className="divide-y divide-border">
          {documentos.map((doc) => (
            <tr key={doc.id} className="align-top hover:bg-accent/40">
              <td className="max-w-sm px-3 py-2.5">
                <a
                  href={`/api/backend/documents/${doc.id}/content`}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {doc.title}
                </a>
                {doc.description ? (
                  <p className="mt-0.5 line-clamp-1 text-muted-foreground">
                    {doc.description}
                  </p>
                ) : null}
              </td>

              <td className="px-3 py-2.5 text-muted-foreground">{doc.category ?? "—"}</td>

              <td className="px-3 py-2.5">
                <StatusBadge status={doc.status} />
              </td>

              {/* Numeros a direita: alinhados na vertical, comparaveis de relance.
                  A fonte ja usa tabular-nums globalmente. */}
              <td className="px-3 py-2.5 text-right text-muted-foreground">
                {doc.version_count}
              </td>
              <td className="px-3 py-2.5 text-right text-muted-foreground">
                {doc.chunk_count ?? "—"}
              </td>

              <td className="whitespace-nowrap px-3 py-2.5 text-muted-foreground">
                {formatarData(doc.updated_at)}
              </td>

              {podeAdministrar ? (
                <td className="px-3 py-2 text-right">
                  {confirmando === doc.id ? (
                    // Confirmacao inline em vez de `confirm()`: nao bloqueia a aba e
                    // mantem o contexto da linha visivel.
                    <div className="flex items-center justify-end gap-1.5">
                      <span className="text-xs text-muted-foreground">Excluir?</span>
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={ocupado === doc.id}
                        onClick={() => agir(doc.id, "delete")}
                      >
                        Sim
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmando(null)}>
                        Nao
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-end gap-0.5">
                      {doc.status === "FAILED" ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          title="Reprocessar"
                          disabled={ocupado === doc.id}
                          onClick={() => agir(doc.id, "reprocess")}
                        >
                          <RotateCw aria-hidden />
                          <span className="sr-only">Reprocessar {doc.title}</span>
                        </Button>
                      ) : null}
                      <Button
                        size="icon"
                        variant="ghost"
                        title="Excluir"
                        disabled={ocupado === doc.id}
                        onClick={() => setConfirmando(doc.id)}
                      >
                        <Trash2 aria-hidden />
                        <span className="sr-only">Excluir {doc.title}</span>
                      </Button>
                    </div>
                  )}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
