/**
 * Valida o destino pos-login.
 *
 * Sem esta checagem, `/login?proximo=https://site-malicioso.com` faria a aplicacao
 * redirecionar o usuario recem-autenticado para fora do dominio — open redirect, que
 * e a base de golpes de phishing ("o link era do sistema da empresa").
 *
 * Aceita apenas caminhos internos: comeca com uma barra e nao com duas (`//host` e
 * interpretado como protocolo-relativo pelo navegador e sairia do dominio).
 */
export function safeNextPath(candidato: string | null | undefined, padrao = "/dashboard"): string {
  if (!candidato) return padrao;
  if (!candidato.startsWith("/")) return padrao;
  if (candidato.startsWith("//")) return padrao;
  if (candidato.includes("\\")) return padrao; // alguns navegadores normalizam \ para /
  return candidato;
}
