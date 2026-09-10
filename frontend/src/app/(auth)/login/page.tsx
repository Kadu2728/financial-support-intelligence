import type { Metadata } from "next";
import { Suspense } from "react";

import { ApiError, backendFetch, UNREACHABLE } from "@/lib/bff";
import { LoginForm } from "@/features/auth/login-form";

export const metadata: Metadata = { title: "Entrar" };
export const dynamic = "force-dynamic";

/**
 * Sem hero, sem ilustracao, sem card flutuante.
 *
 * Esta tela e vista todos os dias por quem ja sabe o que o sistema faz. Seu unico
 * trabalho e sair do caminho. A largura contida e o alinhamento a esquerda favorecem
 * o preenchimento por teclado, que e como o formulario sera realmente usado.
 *
 * O indicador de disponibilidade abaixo e o elemento deliberado desta pagina: quando
 * alguem nao consegue entrar, a primeira duvida e "errei a senha ou o sistema caiu?".
 * Responder isso na propria tela economiza um chamado ao suporte interno.
 */

/**
 * "Fora" e "degradado" nao sao a mesma coisa, e a diferenca muda o que o analista faz.
 *
 * Fora: o servidor nao respondeu — problema de rede ou aplicacao caida, nada a fazer
 * senao esperar. Degradado: o servidor respondeu, mas uma dependencia (o banco) esta
 * indisponivel — o login vai falhar mesmo com a senha certa.
 *
 * Tratar os dois como "indisponivel" desperdicaria exatamente a informacao que
 * justifica este indicador existir.
 */
async function verificarDisponibilidade(): Promise<"ok" | "degradado" | "fora"> {
  try {
    const health = await backendFetch<{ status: string }>("/health/ready", {
      timeoutMs: 4000,
    });
    return health.status === "ready" ? "ok" : "degradado";
  } catch (error) {
    // O readiness responde 503 quando uma dependencia falha: o servidor esta de pe.
    if (error instanceof ApiError && error.code !== UNREACHABLE) {
      return "degradado";
    }
    return "fora";
  }
}

const ESTADOS = {
  ok: { rotulo: "Sistema operacional", cor: "bg-status-ready", aviso: null },
  degradado: {
    rotulo: "Sistema com instabilidade",
    cor: "bg-status-warning",
    aviso: "entrar pode falhar",
  },
  fora: {
    rotulo: "Servidor indisponivel",
    cor: "bg-status-failed",
    aviso: "nao e possivel entrar agora",
  },
} as const;

async function IndicadorDeSistema() {
  const { rotulo, cor, aviso } = ESTADOS[await verificarDisponibilidade()];

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span aria-hidden className={`size-1.5 rounded-full ${cor}`} />
      <span>{rotulo}</span>
      {aviso ? <span className="text-muted-foreground/70">— {aviso}</span> : null}
    </div>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-6 py-12">
      <div className="w-full max-w-[22rem]">
        <header className="mb-8">
          <p className="mb-2 font-mono text-[0.6875rem] uppercase tracking-[0.14em] text-muted-foreground">
            Uso interno
          </p>
          <h1 className="text-xl font-semibold leading-tight tracking-tight text-foreground">
            Financial Support Intelligence
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Consulte politicas e procedimentos internos com as fontes sempre a vista.
          </p>
        </header>

        {/* useSearchParams exige Suspense: sem ele a pagina inteira vira dinamica no
            cliente e o Next avisa no build. */}
        <Suspense fallback={<div className="h-[15.5rem]" />}>
          <LoginForm />
        </Suspense>

        <footer className="mt-8 space-y-3 border-t border-border pt-4">
          <Suspense
            fallback={
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span aria-hidden className="size-1.5 rounded-full bg-status-pending" />
                <span>Verificando o sistema...</span>
              </div>
            }
          >
            <IndicadorDeSistema />
          </Suspense>

          <p className="text-xs leading-relaxed text-muted-foreground">
            Acessos sao registrados. Use suas credenciais corporativas e nao as
            compartilhe.
          </p>
        </footer>
      </div>
    </main>
  );
}
