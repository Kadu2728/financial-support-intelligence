import type { Metadata } from "next";

import { CopilotPanel } from "@/features/copilot/copilot-panel";
import { getCapabilities } from "@/lib/capabilities";

export const metadata: Metadata = { title: "Copiloto" };
export const dynamic = "force-dynamic";

export default async function CopilotPage() {
  const { gemini } = await getCapabilities();

  return (
    <div className="space-y-6">
      <header className="mx-auto max-w-3xl">
        <h1 className="text-lg font-semibold tracking-tight">Copiloto</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Respostas fundamentadas nos documentos internos, com a fonte de cada afirmacao.
          Quando o acervo nao cobre o tema, o copiloto diz isso em vez de arriscar.
        </p>
      </header>
      <CopilotPanel gemini_configured={gemini} />
    </div>
  );
}
