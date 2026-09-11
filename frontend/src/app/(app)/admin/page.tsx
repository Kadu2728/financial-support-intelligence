import type { Metadata } from "next";

import { CreateUserForm } from "@/features/admin/create-user-form";
import { getCurrentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Usuarios" };
export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const user = await getCurrentUser();

  if (user?.role !== "ADMIN") {
    // Mesma barreira do backend (require_role). Aqui e so para nao mostrar um
    // formulario que devolveria 403.
    return (
      <div className="rounded-lg border border-border px-4 py-10 text-center">
        <p className="text-sm font-medium">Esta tela e restrita a administradores.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-lg font-semibold tracking-tight">Usuarios</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Cadastro de analistas e administradores. Nao existe auto-registro: todo acesso
          e concedido por um administrador.
        </p>
      </header>
      <CreateUserForm />
    </div>
  );
}
