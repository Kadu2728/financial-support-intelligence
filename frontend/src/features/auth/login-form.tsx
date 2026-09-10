"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { safeNextPath } from "@/lib/redirect";

/**
 * Mensagens por codigo de erro.
 *
 * O backend define `code` como contrato estavel (app/core/errors.py) justamente para
 * que o cliente escolha a mensagem. Repassar o texto do servidor funcionaria, mas
 * amarraria a UI ao idioma e ao tom de outra camada.
 */
const SEM_CONEXAO = "Nao foi possivel conectar ao servidor. Tente novamente.";
const PADRAO = "Nao foi possivel entrar. Tente novamente.";

const MENSAGENS: Record<string, string> = {
  INVALID_CREDENTIALS: "E-mail ou senha incorretos.",
  INACTIVE_USER: "Esta conta esta desativada. Procure um administrador.",
  VALIDATION_ERROR: "Verifique o e-mail informado.",
  RATE_LIMITED: "Muitas tentativas. Aguarde um instante antes de tentar de novo.",
  BACKEND_UNREACHABLE: SEM_CONEXAO,
  // Falha do lado do servidor: a senha do usuario pode estar certa. Dizer isso evita
  // que ele tente redefinir uma credencial que nao tem problema nenhum.
  INTERNAL_ERROR: "O sistema esta indisponivel no momento. Tente novamente em instantes.",
};

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();

  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErro(null);
    setEnviando(true);

    const dados = new FormData(event.currentTarget);

    try {
      const resposta = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: String(dados.get("email") ?? "").trim(),
          password: String(dados.get("password") ?? ""),
        }),
      });

      if (!resposta.ok) {
        const corpo = await resposta.json().catch(() => null);
        const codigo = corpo?.error?.code as string | undefined;
        setErro((codigo && MENSAGENS[codigo]) ?? PADRAO);
        setEnviando(false);
        return;
      }

      // `refresh` garante que o Server Component do layout releia a sessao; sem ele o
      // cabecalho renderizaria com o cache anterior, sem o usuario.
      router.replace(safeNextPath(params.get("proximo")));
      router.refresh();
    } catch {
      setErro(SEM_CONEXAO);
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <div className="space-y-1.5">
        <Label htmlFor="email">E-mail corporativo</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          autoFocus
          disabled={enviando}
          aria-invalid={erro !== null}
          placeholder="nome@instituicao.com.br"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="password">Senha</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          disabled={enviando}
          aria-invalid={erro !== null}
        />
      </div>

      {/* aria-live: quem usa leitor de tela ouve o erro sem precisar navegar ate ele. */}
      <div aria-live="polite" className="min-h-5">
        {erro ? (
          <p className="flex items-start gap-2 text-sm text-destructive">
            <span aria-hidden className="mt-px select-none font-mono">
              !
            </span>
            {erro}
          </p>
        ) : null}
      </div>

      <Button type="submit" disabled={enviando} className="w-full">
        {enviando ? "Entrando..." : "Entrar"}
      </Button>
    </form>
  );
}
