"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Identificacao do usuario e saida.
 *
 * O papel fica visivel de proposito: quem opera como ADMIN precisa saber disso antes
 * de executar uma acao destrutiva, sem ter que abrir um menu para lembrar.
 */
export function UserMenu({
  name,
  email,
  role,
}: {
  name: string;
  email: string;
  role: "ADMIN" | "ANALYST";
}) {
  const router = useRouter();
  const [saindo, setSaindo] = useState(false);

  async function sair() {
    setSaindo(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      // Mesmo se a chamada falhar, o cookie ja foi apagado no servidor — seguir para
      // o login e o comportamento correto em qualquer cenario.
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <div className="flex items-center gap-3">
      <div className="hidden text-right leading-tight sm:block">
        <p className="text-sm font-medium">{name}</p>
        <p className="text-xs text-muted-foreground">
          {email}
          <span className="mx-1.5 text-border">|</span>
          <span className="font-mono text-[0.625rem] uppercase tracking-wider">
            {role === "ADMIN" ? "Administrador" : "Analista"}
          </span>
        </p>
      </div>

      <Button variant="outline" size="sm" onClick={sair} disabled={saindo}>
        {saindo ? "Saindo..." : "Sair"}
      </Button>
    </div>
  );
}
