import { NextResponse, type NextRequest } from "next/server";

/**
 * Guarda de rotas.
 *
 * Verifica apenas a PRESENCA do cookie de sessao, nunca a validade do token. Validar
 * exigiria o segredo do JWT no Edge runtime, e duplicar a politica de autorizacao em
 * dois lugares — que e como as duas acabam divergindo.
 *
 * A autorizacao real acontece no backend, a cada requisicao. Este middleware existe
 * para UX: evitar que o usuario sem sessao veja um layout piscar antes de ser
 * redirecionado. Um cookie forjado passa por aqui e e recusado pelo backend em
 * seguida, sem dado nenhum vazado.
 */

const REFRESH_COOKIE = "fsi_refresh";
const LOGIN = "/login";

// Rotas publicas. Todo o resto exige sessao.
const PUBLICAS = new Set([LOGIN]);

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const temSessao = request.cookies.has(REFRESH_COOKIE);
  const ehPublica = PUBLICAS.has(pathname);

  if (!temSessao && !ehPublica) {
    const url = request.nextUrl.clone();
    url.pathname = LOGIN;
    url.search = "";
    // Preserva o destino para devolver o usuario onde ele queria chegar. Guardado
    // como parametro relativo; `lib/redirect.ts` recusa URLs absolutas na volta.
    if (pathname !== "/") {
      url.searchParams.set("proximo", `${pathname}${search}`);
    }
    return NextResponse.redirect(url);
  }

  if (temSessao && ehPublica) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  /**
   * Exclui as rotas do BFF: elas precisam responder 401 em JSON para o cliente
   * tratar, nao redirecionar para uma pagina HTML — um fetch que recebe HTML no
   * lugar de JSON falha de forma confusa.
   */
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
