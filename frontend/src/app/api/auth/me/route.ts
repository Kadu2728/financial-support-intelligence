import { NextResponse } from "next/server";

import { ApiError } from "@/lib/bff";
import { authenticatedFetch, type UserProfile } from "@/lib/session";

/** Perfil do usuario logado. Renova a sessao automaticamente se o access expirou. */
export async function GET(request: Request) {
  const requestId = request.headers.get("x-request-id");

  try {
    const user = await authenticatedFetch<UserProfile>("/api/v1/auth/me", { requestId });
    return NextResponse.json(user);
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(
        { error: { code: error.code, message: error.message } },
        { status: error.status },
      );
    }
    throw error;
  }
}
