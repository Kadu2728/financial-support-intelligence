import { ApiError, backendFetch } from "@/lib/bff";
import { cn } from "@/lib/utils";

/**
 * Pagina de verificacao da Fase 1.
 *
 * Sera substituida pelo redirecionamento para /dashboard na Fase 3. Existe agora para
 * provar que a cadeia Next -> FastAPI funciona, e para exercitar os estados de erro
 * desde o inicio: se o backend estiver fora, a pagina precisa dizer isso com clareza,
 * nao quebrar.
 *
 * Este e um Server Component, entao chama `backendFetch` diretamente. A rota
 * /api/health existe para o caso oposto: Client Components, que passam pelo BFF.
 */

export const dynamic = "force-dynamic";

interface BackendHealth {
  status: string;
  checks: Record<string, unknown>;
}

type CheckResult =
  | { ok: true; detail: string }
  | { ok: false; detail: string; hint?: string };

async function checkBackend(): Promise<CheckResult> {
  try {
    const health = await backendFetch<BackendHealth>("/health/ready");
    return { ok: true, detail: `respondeu "${health.status}"` };
  } catch (error) {
    if (error instanceof ApiError) {
      return {
        ok: false,
        detail: error.message,
        hint: "Inicie o backend: cd backend && uvicorn app.main:app --reload",
      };
    }
    return { ok: false, detail: "Falha inesperada ao verificar o backend." };
  }
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={cn(
        // `block` e obrigatorio: em um <span> inline, width/height sao ignoradas pelo
        // layout — o elemento fica 0x0 e some, mesmo com o computed style reportando 8px.
        "mt-1.5 block size-2 shrink-0 rounded-full",
        ok ? "bg-status-ready" : "bg-status-failed",
      )}
      aria-hidden
    />
  );
}

function CheckRow({
  label,
  result,
}: {
  label: string;
  result: CheckResult;
}) {
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <StatusDot ok={result.ok} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="text-sm font-medium">{label}</span>
          <span
            className={cn(
              "font-mono text-xs",
              result.ok ? "text-muted-foreground" : "text-destructive",
            )}
          >
            {result.ok ? "OK" : "INDISPONIVEL"}
          </span>
        </div>
        <p className="mt-0.5 text-sm text-muted-foreground">{result.detail}</p>
        {!result.ok && result.hint ? (
          <p className="mt-2 rounded-md bg-muted px-2.5 py-1.5 font-mono text-xs text-muted-foreground">
            {result.hint}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export default async function Home() {
  const backend = await checkBackend();

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center px-6 py-16">
      <header>
        <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
          Fase 1 · Setup
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-balance">
          Financial Support Intelligence
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Inteligencia operacional sobre documentos internos para equipes de suporte.
        </p>
      </header>

      <section className="mt-8" aria-labelledby="status-heading">
        <h2
          id="status-heading"
          className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase"
        >
          Verificacao do ambiente
        </h2>
        <div className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-card">
          <CheckRow
            label="Frontend"
            result={{ ok: true, detail: "Next.js 16 · React 19 · Tailwind v4" }}
          />
          <CheckRow label="Backend" result={backend} />
        </div>
      </section>

      <footer className="mt-8 border-t border-border pt-4">
        <p className="text-sm text-muted-foreground">
          Proxima fase: banco de dados, migrations e pgvector.
        </p>
      </footer>
    </main>
  );
}
