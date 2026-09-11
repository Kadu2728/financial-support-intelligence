import type { Metadata } from "next";

import { SearchPanel } from "@/features/search/search-panel";
import { getCapabilities } from "@/lib/capabilities";

export const metadata: Metadata = { title: "Busca" };
export const dynamic = "force-dynamic";

export default async function SearchPage() {
  const { gemini } = await getCapabilities();

  return (
    <div className="space-y-6">
      <header className="mx-auto max-w-4xl">
        <h1 className="text-lg font-semibold tracking-tight">Busca no acervo</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Trechos dos documentos, sem redacao pelo modelo. Util para conferir a fonte de
          uma resposta ou localizar um codigo exato.
        </p>
      </header>
      <SearchPanel gemini_configured={gemini} />
    </div>
  );
}
