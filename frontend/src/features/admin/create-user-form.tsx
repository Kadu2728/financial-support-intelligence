"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Cadastro de usuario pelo administrador.
 *
 * Nao existe auto-registro: numa ferramenta interna de banco, quem entra e decidido
 * por alguem com autoridade para isso. A senha inicial e definida aqui e o usuario
 * deve troca-la — a troca de senha pelo proprio usuario fica registrada como
 * melhoria, nao como requisito da v1.
 */
const MENSAGENS: Record<string, string> = {
  CONFLICT: "Ja existe um usuario com este e-mail.",
  VALIDATION_ERROR: "Confira os campos: e-mail valido, nome e senha com 12+ caracteres.",
  FORBIDDEN: "Apenas administradores podem cadastrar usuarios.",
};

export function CreateUserForm() {
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [criado, setCriado] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const dados = new FormData(form);
    setEnviando(true);
    setErro(null);
    setCriado(null);

    try {
      const res = await fetch("/api/backend/users", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email: dados.get("email"),
          full_name: dados.get("full_name"),
          password: dados.get("password"),
          role: dados.get("role"),
        }),
      });
      if (!res.ok) {
        const corpo = await res.json().catch(() => null);
        const codigo = corpo?.error?.code as string | undefined;
        setErro((codigo && MENSAGENS[codigo]) ?? "Nao foi possivel cadastrar o usuario.");
        return;
      }
      const perfil = (await res.json()) as { email: string; role: string };
      setCriado(`${perfil.email} cadastrado como ${perfil.role}.`);
      form.reset();
    } catch {
      setErro("Falha de conexao. Tente novamente.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-md space-y-4 rounded-lg border border-border p-4">
      <div className="space-y-1.5">
        <Label htmlFor="full_name">Nome completo</Label>
        <Input id="full_name" name="full_name" required minLength={2} maxLength={255} autoComplete="off" />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="email">E-mail</Label>
        <Input id="email" name="email" type="email" required autoComplete="off" />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="password">Senha inicial</Label>
        <Input
          id="password"
          name="password"
          type="password"
          required
          minLength={12}
          maxLength={128}
          autoComplete="new-password"
        />
        <p className="text-xs text-muted-foreground">Minimo de 12 caracteres.</p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="role">Papel</Label>
        <select
          id="role"
          name="role"
          defaultValue="ANALYST"
          className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="ANALYST">Analista — consulta e busca</option>
          <option value="ADMIN">Administrador — tambem gerencia acervo e usuarios</option>
        </select>
      </div>

      {erro ? (
        <p role="alert" className="text-sm text-destructive">
          {erro}
        </p>
      ) : null}
      {criado ? (
        <p role="status" className="text-sm text-status-ready">
          {criado}
        </p>
      ) : null}

      <Button type="submit" disabled={enviando}>
        {enviando ? "Cadastrando…" : "Cadastrar usuario"}
      </Button>
    </form>
  );
}
