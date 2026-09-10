import { redirect } from "next/navigation";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { UserMenu } from "@/components/layout/user-menu";
import { getCurrentUser } from "@/lib/session";

/**
 * Shell das telas autenticadas.
 *
 * A sessao e resolvida aqui, uma vez por navegacao, e o usuario desce por props. Cada
 * pagina buscar o proprio perfil produziria uma chamada a `/auth/me` por rota, todas
 * com a mesma resposta.
 *
 * O middleware ja redireciona quem nao tem cookie; esta verificacao cobre o caso de
 * cookie presente mas sessao invalida — que o middleware nao consegue distinguir sem
 * validar o token.
 */
export default async function AppLayout({ children }: LayoutProps<"/">) {
  const user = await getCurrentUser();

  if (!user) {
    redirect("/login");
  }

  return (
    <div className="flex min-h-dvh">
      <AppSidebar role={user.role} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-border px-4 md:px-6">
          <div className="min-w-0" />
          <UserMenu name={user.full_name} email={user.email} role={user.role} />
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 md:px-6">{children}</main>
      </div>
    </div>
  );
}
