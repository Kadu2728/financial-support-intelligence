import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AnswerCard } from "@/features/copilot/answer-card";
import type { QueryDetail } from "@/features/copilot/types";
import { formatarData } from "@/features/documents/types";
import { ApiError } from "@/lib/bff";
import { authenticatedFetch } from "@/lib/session";

export const metadata: Metadata = { title: "Consulta" };
export const dynamic = "force-dynamic";

export default async function QueryDetailPage({ params }: PageProps<"/history/[id]">) {
  const { id } = await params;

  let consulta: QueryDetail;
  try {
    consulta = await authenticatedFetch<QueryDetail>(`/api/v1/queries/${id}`);
  } catch (error) {
    // 404 cobre tanto "nao existe" quanto "e de outro usuario": o backend nao
    // distingue de proposito, e a tela tambem nao deve.
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <nav className="text-xs text-muted-foreground">
        <Link href="/history" className="hover:text-foreground">
          Historico
        </Link>{" "}
        / {formatarData(consulta.created_at)}
        {consulta.model ? ` · ${consulta.model}` : ""}
      </nav>
      <AnswerCard consulta={consulta} />
    </div>
  );
}
