import "server-only";

/**
 * Configuracao lida apenas no servidor.
 *
 * O import de `server-only` faz o build falhar se este modulo for alcancado por um
 * Client Component. E uma barreira em tempo de compilacao contra o erro de vazar
 * configuracao de servidor para o bundle do navegador — que e o modo silencioso de
 * anular o BFF (ADR-0003).
 */

function required(name: string, value: string | undefined): string {
  if (!value) {
    // Falha na inicializacao, nao no meio de um request em producao.
    throw new Error(
      `Variavel de ambiente obrigatoria ausente: ${name}. Veja frontend/.env.example.`,
    );
  }
  return value;
}

export const serverConfig = {
  backendUrl: required(
    "BACKEND_URL",
    process.env.BACKEND_URL ?? "http://localhost:8000",
  ).replace(/\/$/, ""),
} as const;
