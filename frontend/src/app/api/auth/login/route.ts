import { NextResponse } from "next/server";

import { ApiError, backendFetch, REQUEST_ID_HEADER } from "@/lib/bff";
import { saveSession, type TokenPair, type UserProfile } from "@/lib/session";

/**
 * Troca credenciais por uma sessao em cookie httpOnly.
 *
 * Os tokens vindos do backend sao gravados aqui e NAO devolvidos ao navegador — a
 * resposta carrega apenas o perfil. E isso que impede um XSS de roubar a sessao.
 */

interface LoginResponse {
  tokens: TokenPair;
  user: UserProfile;
}

export async function POST(request: Request) {
  const requestId = request.headers.get(REQUEST_ID_HEADER);

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: { code: "VALIDATION_ERROR", message: "Requisicao malformada." } },
      { status: 400 },
    );
  }

  try {
    const resposta = await backendFetch<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: payload,
      requestId,
    });

    await saveSession(resposta.tokens);
    return NextResponse.json({ user: resposta.user });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(
        { error: { code: error.code, message: error.message, details: error.details } },
        { status: error.status },
      );
    }
    throw error;
  }
}
