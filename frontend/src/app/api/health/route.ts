import { NextResponse } from "next/server";

import { ApiError, backendFetch, REQUEST_ID_HEADER } from "@/lib/bff";

/**
 * Primeira rota do BFF. Existe para validar o caminho browser -> Next -> FastAPI de
 * ponta a ponta, e serve de molde para as rotas de dominio das proximas fases.
 */

interface BackendHealth {
  status: string;
  checks: Record<string, unknown>;
}

export async function GET(request: Request) {
  const requestId = request.headers.get(REQUEST_ID_HEADER);

  try {
    const backend = await backendFetch<BackendHealth>("/health/ready", { requestId });
    return NextResponse.json({ frontend: "ok", backend });
  } catch (error) {
    if (error instanceof ApiError) {
      // O status do backend e repassado como esta: o cliente distingue "backend
      // fora do ar" (502/504) de "backend respondeu com erro".
      return NextResponse.json(
        {
          frontend: "ok",
          backend: null,
          error: { code: error.code, message: error.message },
        },
        { status: error.status },
      );
    }
    throw error;
  }
}
