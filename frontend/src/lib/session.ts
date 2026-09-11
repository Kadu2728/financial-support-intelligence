import "server-only";

import { cookies } from "next/headers";

import { ApiError, backendFetch, REQUEST_ID_HEADER } from "@/lib/bff";
import { serverConfig } from "@/lib/server-config";

/**
 * Sessao em cookies httpOnly first-party (ADR-0003).
 *
 * Os tokens nunca chegam ao JavaScript do navegador: sao gravados aqui, no servidor
 * do Next, e reanexados como `Authorization` a cada chamada ao FastAPI. Um XSS na
 * aplicacao nao consegue ler a credencial.
 */

const ACCESS_COOKIE = "fsi_access";
const REFRESH_COOKIE = "fsi_refresh";

const REFRESH_MAX_AGE = 60 * 60 * 24 * 7; // espelha REFRESH_TOKEN_EXPIRE_DAYS no backend

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: "ADMIN" | "ANALYST";
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

const baseCookie = {
  httpOnly: true,
  // Lax, nao Strict: com Strict o cookie nao acompanha navegacao vinda de um link
  // externo, e o usuario que clica no link de um chamado cai na tela de login mesmo
  // com sessao valida. O cookie e first-party, entao CSRF ja e mitigado pela origem.
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

export async function saveSession(tokens: TokenPair): Promise<void> {
  const jar = await cookies();

  jar.set(ACCESS_COOKIE, tokens.access_token, {
    ...baseCookie,
    maxAge: tokens.expires_in,
  });
  jar.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...baseCookie,
    maxAge: REFRESH_MAX_AGE,
  });
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
}

export async function readTokens(): Promise<{
  access: string | null;
  refresh: string | null;
}> {
  const jar = await cookies();
  return {
    access: jar.get(ACCESS_COOKIE)?.value ?? null,
    refresh: jar.get(REFRESH_COOKIE)?.value ?? null,
  };
}

/**
 * Chama o backend autenticado, renovando a sessao quando o access token expirou.
 *
 * O access dura 15 minutos e o refresh 7 dias — sem esta renovacao, o usuario seria
 * deslogado a cada 15 minutos de uso. A rotacao acontece no backend; aqui apenas
 * gravamos o par novo.
 *
 * Só funciona em Route Handlers e Server Actions: fora deles o Next nao permite
 * escrever cookies. Por isso toda leitura autenticada do cliente passa pelo BFF.
 */
export async function authenticatedFetch<T>(
  path: string,
  options: { method?: string; body?: unknown; requestId?: string | null } = {},
): Promise<T> {
  const { access, refresh } = await readTokens();

  if (access) {
    try {
      return await backendFetch<T>(path, { ...options, token: access });
    } catch (error) {
      const expirou =
        error instanceof ApiError &&
        error.status === 401 &&
        refresh !== null;
      if (!expirou) throw error;
    }
  }

  if (!refresh) {
    throw new ApiError(401, "TOKEN_INVALID", "Sessao expirada. Faca login novamente.");
  }

  let renovados: TokenPair;
  try {
    renovados = await backendFetch<TokenPair>("/api/v1/auth/refresh", {
      method: "POST",
      body: { refresh_token: refresh },
    });
  } catch (error) {
    // Refresh recusado significa sessao encerrada, expirada — ou reuso detectado, que
    // o backend trata derrubando todas as sessoes. Em qualquer caso, limpar os cookies
    // evita um laco de tentativas com credencial morta.
    await clearSession();
    throw error;
  }

  await saveSession(renovados);
  return backendFetch<T>(path, { ...options, token: renovados.access_token });
}

/**
 * Encaminha uma requisicao do navegador ao backend, anexando o token.
 *
 * Repassa o corpo sem interpreta-lo: upload de documento chega como multipart, e
 * desserializar para reserializar quebraria o boundary e ainda carregaria o arquivo
 * inteiro na memoria do Next.
 */
export async function proxyToBackend(path: string, request: Request): Promise<Response> {
  const { access, refresh } = await readTokens();

  const corpo =
    request.method === "GET" || request.method === "DELETE"
      ? undefined
      : await request.arrayBuffer();

  // O Content-Type original precisa sobreviver — no multipart ele carrega o boundary.
  const cabecalhos: Record<string, string> = {};
  const tipo = request.headers.get("content-type");
  if (tipo) cabecalhos["content-type"] = tipo;
  const requestId = request.headers.get(REQUEST_ID_HEADER);
  if (requestId) cabecalhos[REQUEST_ID_HEADER] = requestId;

  async function chamar(token: string | null): Promise<Response> {
    return fetch(`${serverConfig.backendUrl}${path}`, {
      method: request.method,
      headers: { ...cabecalhos, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: corpo,
      cache: "no-store",
    });
  }

  let resposta = access ? await chamar(access) : null;

  if ((resposta === null || resposta.status === 401) && refresh) {
    // Access expirado: renova e repete. Sem isto o usuario seria deslogado a cada
    // 15 minutos de uso.
    try {
      const renovados = await backendFetch<TokenPair>("/api/v1/auth/refresh", {
        method: "POST",
        body: { refresh_token: refresh },
      });
      await saveSession(renovados);
      resposta = await chamar(renovados.access_token);
    } catch (error) {
      await clearSession();
      throw error;
    }
  }

  if (resposta === null) {
    throw new ApiError(401, "TOKEN_INVALID", "Sessao expirada. Faca login novamente.");
  }

  // O corpo e repassado como stream: um PDF de 20 MB nao precisa ser bufferizado aqui.
  return new Response(resposta.body, {
    status: resposta.status,
    headers: {
      "content-type": resposta.headers.get("content-type") ?? "application/json",
      ...(resposta.headers.get("content-disposition")
        ? { "content-disposition": resposta.headers.get("content-disposition")! }
        : {}),
    },
  });
}

/** Perfil do usuario logado, ou null quando nao ha sessao valida. */
export async function getCurrentUser(): Promise<UserProfile | null> {
  const { access, refresh } = await readTokens();
  if (!access && !refresh) return null;

  try {
    return await authenticatedFetch<UserProfile>("/api/v1/auth/me");
  } catch {
    return null;
  }
}

export { ACCESS_COOKIE, REFRESH_COOKIE };
