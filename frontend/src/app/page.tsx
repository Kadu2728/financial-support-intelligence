import { redirect } from "next/navigation";

/**
 * A raiz nao tem conteudo proprio.
 *
 * Quem chega aqui com sessao vai para o painel; quem chega sem sessao e desviado
 * pelo middleware antes de este componente executar.
 */
export default function RootPage() {
  redirect("/dashboard");
}
