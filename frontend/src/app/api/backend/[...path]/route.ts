import { NextResponse } from "next/server";

import { ApiError, REQUEST_ID_HEADER } from "@/lib/bff";
import { proxyToBackend } from "@/lib/session";

/**
 * Proxy autenticado para a API.
 *
 * Encaminha `/api/backend/*` para o FastAPI anexando o token do cookie httpOnly.
 * Uma rota explicita por endpoint duplicaria a superficie inteira da API sem
 * acrescentar seguranca: a autorizacao vive no backend, que valida papel e posse em
 * TODA requisicao. O BFF so resolve a credencial (ADR-0003).
 *
 * As rotas de `/api/auth/*` permanecem explicitas porque tem logica propria — gravar e
 * limpar cookie —, que nao e proxy.
 */

async function encaminhar(request: Request, contexto: RouteContext<"/api/backend/[...path]">) {
  const { path } = await contexto.params;
  const url = new URL(request.url);
  const destino = `/api/v1/${path.join("/")}${url.search}`;

  try {
    return await proxyToBackend(destino, request);
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(
        { error: { code: error.code, message: error.message, details: error.details } },
        { status: error.status, headers: { [REQUEST_ID_HEADER]: error.requestId ?? "" } },
      );
    }
    throw error;
  }
}

export const GET = encaminhar;
export const POST = encaminhar;
export const PATCH = encaminhar;
export const PUT = encaminhar;
export const DELETE = encaminhar;
