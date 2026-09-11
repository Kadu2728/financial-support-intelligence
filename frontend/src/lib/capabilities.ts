import "server-only";

import { backendFetch } from "@/lib/bff";

interface Readiness {
  status: string;
  checks: Record<string, string>;
}

/**
 * O que o backend consegue fazer agora. Vem do readiness, que e publico e nao
 * exige sessao: o frontend avisa o analista que o copilot esta desligado ANTES
 * de ele digitar uma pergunta e receber um 503.
 */
export async function getCapabilities(): Promise<{ gemini: boolean; database: boolean }> {
  try {
    const dados = await backendFetch<Readiness>("/health/ready");
    return {
      gemini: dados.checks.gemini === "configured",
      database: dados.checks.database === "ok",
    };
  } catch {
    return { gemini: false, database: false };
  }
}
