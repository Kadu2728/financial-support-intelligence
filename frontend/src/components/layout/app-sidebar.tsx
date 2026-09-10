"use client";

import {
  BarChart3,
  FileText,
  History,
  LayoutDashboard,
  MessageSquareText,
  Search,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * Navegacao primaria.
 *
 * Fixa e sempre visivel: o analista alterna entre Copiloto, Busca e Documentos dezenas
 * de vezes por turno, e um menu que precisa ser aberto cobra um clique a cada troca.
 *
 * Os itens de ADMIN sao filtrados aqui por clareza, nao por seguranca — a barreira
 * real esta no backend (`require_role`). Esconder no cliente apenas evita mostrar
 * caminhos que levariam a um 403.
 */

interface ItemNav {
  href: string;
  rotulo: string;
  Icone: typeof LayoutDashboard;
  somenteAdmin?: boolean;
}

const PRINCIPAIS: ItemNav[] = [
  { href: "/dashboard", rotulo: "Painel", Icone: LayoutDashboard },
  { href: "/copilot", rotulo: "Copiloto", Icone: MessageSquareText },
  { href: "/search", rotulo: "Busca", Icone: Search },
  { href: "/history", rotulo: "Historico", Icone: History },
];

const GESTAO: ItemNav[] = [
  { href: "/documents", rotulo: "Documentos", Icone: FileText },
  { href: "/intelligence", rotulo: "Inteligencia", Icone: BarChart3 },
  { href: "/admin", rotulo: "Usuarios", Icone: Users, somenteAdmin: true },
];

function Grupo({
  titulo,
  itens,
  ativo,
}: {
  titulo: string;
  itens: ItemNav[];
  ativo: string;
}) {
  if (itens.length === 0) return null;

  return (
    <div className="space-y-1">
      <p className="px-2 py-1 font-mono text-[0.625rem] uppercase tracking-[0.12em] text-muted-foreground">
        {titulo}
      </p>
      {itens.map(({ href, rotulo, Icone }) => {
        const selecionado = ativo === href || ativo.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={selecionado ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              selecionado
                ? "bg-accent font-medium text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            )}
          >
            <Icone aria-hidden className="size-4 shrink-0" />
            {rotulo}
          </Link>
        );
      })}
    </div>
  );
}

export function AppSidebar({ role }: { role: "ADMIN" | "ANALYST" }) {
  const pathname = usePathname();
  const gestao = GESTAO.filter((item) => !item.somenteAdmin || role === "ADMIN");

  return (
    <nav
      aria-label="Navegacao principal"
      className="hidden w-56 shrink-0 flex-col gap-6 border-r border-border px-3 py-4 md:flex"
    >
      <div className="px-2">
        <p className="text-sm font-semibold leading-tight tracking-tight">
          Financial Support
        </p>
        <p className="font-mono text-[0.625rem] uppercase tracking-[0.12em] text-muted-foreground">
          Intelligence
        </p>
      </div>

      <div className="space-y-5">
        <Grupo titulo="Operacao" itens={PRINCIPAIS} ativo={pathname} />
        <Grupo titulo="Gestao" itens={gestao} ativo={pathname} />
      </div>
    </nav>
  );
}
