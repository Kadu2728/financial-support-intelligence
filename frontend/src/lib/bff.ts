import "server-only";

import { serverConfig } from "@/lib/server-config";

/**
 * Camada BFF: o unico ponto por onde o Next fala com o FastAPI.
 *
 * O navegador chama `/api/*` na propria origem; este modulo encaminha para o backend.
 * A partir da Fase 3 e aqui que o token sai do cookie httpOnly e vira o header
 * `Authorization` — o cliente nunca ve a credencial. Ver ADR-0003.
 */

export const REQUEST_ID_HEADER = "x-request-id";

/** Envelope de erro do backend. Espelha `app/core/errors.py` — se um mudar, o outro quebra. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string | null;
  };
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Erro de transporte: o backend nao respondeu. Distinto de um erro devolvido por ele. */
export const UNREACHABLE = "BACKEND_UNREACHABLE";

interface BackendRequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Encaminha o request-id do browser para manter a correlacao ponta a ponta. */
  requestId?: string | null;
  timeoutMs?: number;
}

export async function backendFetch<T>(
  path: string,
  options: BackendRequestOptions = {},
): Promise<T> {
  const { body, requestId, timeoutMs = 30_000, headers, ...init } = options;

  // Sem timeout explicito, um backend lento prende o runtime do Next ate o limite da
  // plataforma e o usuario fica olhando para um spinner sem fim.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${serverConfig.backendUrl}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(requestId ? { [REQUEST_ID_HEADER]: requestId } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch (cause) {
    const timedOut = cause instanceof Error && cause.name === "AbortError";
    throw new ApiError(
      timedOut ? 504 : 502,
      UNREACHABLE,
      timedOut
        ? "O servidor demorou demais para responder."
        : "Nao foi possivel conectar ao servidor.",
    );
  } finally {
    clearTimeout(timeout);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const envelope = payload as ApiErrorBody | null;
    throw new ApiError(
      response.status,
      envelope?.error?.code ?? "INTERNAL_ERROR",
      envelope?.error?.message ?? "Erro inesperado.",
      envelope?.error?.details ?? {},
      envelope?.error?.request_id ?? response.headers.get(REQUEST_ID_HEADER),
    );
  }

  return payload as T;
}
