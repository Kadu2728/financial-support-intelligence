import type { Metadata } from "next";

import "./globals.css";

/**
 * Tipografia: system font stack, sem `next/font/google`.
 *
 * `next/font/google` baixa a fonte em tempo de BUILD. Isso torna o build dependente
 * da disponibilidade de fonts.googleapis.com — um build que quebra por indisponibilidade
 * de terceiro e fragilidade real de CI, nao hipotese.
 *
 * Para uma ferramenta interna usada o dia inteiro, a fonte do sistema tambem entrega
 * renderizacao imediata (sem FOUT/FOIT) e legibilidade nativa em cada SO.
 *
 * Custo: nao ha identidade tipografica propria, e a renderizacao difere entre
 * plataformas. Para reverter mantendo o build offline, baixe os .woff2 do Geist,
 * versione em `src/assets/fonts/` e use `next/font/local` — o melhor dos dois lados.
 */

export const metadata: Metadata = {
  title: {
    default: "Financial Support Intelligence",
    template: "%s · Financial Support Intelligence",
  },
  description:
    "Inteligencia operacional sobre documentos internos para equipes de suporte.",
  // Ferramenta interna: nao deve ser indexada nem aparecer em busca publica.
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" className="h-full antialiased" suppressHydrationWarning>
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
