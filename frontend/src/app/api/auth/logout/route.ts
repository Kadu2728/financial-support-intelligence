import { NextResponse } from "next/server";

import { backendFetch } from "@/lib/bff";
import { clearSession, readTokens } from "@/lib/session";

/**
 * Encerra a sessao nos dois lados.
 *
 * O cookie e apagado SEMPRE, mesmo se o backend falhar: o usuario pediu para sair, e
 * deixar a credencial no navegador porque uma chamada de rede falhou seria o pior
 * resultado possivel. O token orfao expira sozinho em ate 7 dias.
 */
export async function POST() {
  const { refresh } = await readTokens();

  if (refresh) {
    try {
      await backendFetch("/api/v1/auth/logout", {
        method: "POST",
        body: { refresh_token: refresh },
      });
    } catch {
      // Registrado como aceitavel acima.
    }
  }

  await clearSession();
  return NextResponse.json({ ok: true });
}
