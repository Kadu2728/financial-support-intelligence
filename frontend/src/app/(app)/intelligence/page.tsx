import type { Metadata } from "next";
import Link from "next/link";

import { MOTIVOS, type FeedbackReason, formatarMs } from "@/features/copilot/types";
import { formatarData } from "@/features/documents/types";
import { type Overview, pct } from "@/features/intelligence/types";
import { ApiError } from "@/lib/bff";
import { authenticatedFetch } from "@/lib/session";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Inteligencia" };
export const dynamic = "force-dynamic";

const JANELAS = [7, 30, 90];

/**
 * Support Intelligence.
 *
 * Todo numero desta tela vem de uma agregacao no banco (`/intelligence/overview`).
 * Quando a amostra e pequena demais para uma taxa significar algo, a taxa vem nula
 * e a tela mostra "—" com a explicacao — nunca um percentual sobre tres consultas.
 */
export default async function IntelligencePage({ searchParams }: PageProps<"/intelligence">) {
  const params = await searchParams;
  const dias = JANELAS.includes(Number(params.dias)) ? Number(params.dias) : 30;

  let dados: Overview | null = null;
  let erro: { status: number; mensagem: string } | null = null;
  try {
    dados = await authenticatedFetch<Overview>(`/api/v1/intelligence/overview?dias=${dias}`);
  } catch (error) {
    erro =
      error instanceof ApiError
        ? { status: error.status, mensagem: error.message }
        : { status: 0, mensagem: "Nao foi possivel carregar os indicadores." };
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Inteligencia de suporte</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            O que o acervo responde, o que nao responde, e com que qualidade. Somente
            metricas medidas.
          </p>
        </div>
        <nav className="flex gap-1 text-xs" aria-label="Periodo">
          {JANELAS.map((janela) => (
            <Link
              key={janela}
              href={`/intelligence?dias=${janela}`}
              className={cn(
                "rounded-md border px-2.5 py-1",
                janela === dias
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {janela} dias
            </Link>
          ))}
        </nav>
      </header>

      {erro ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm">
          <p className="font-medium text-destructive">
            {erro.status === 403 ? "Esta tela e restrita a administradores." : erro.mensagem}
          </p>
        </div>
      ) : dados ? (
        <Painel dados={dados} />
      ) : null}
    </div>
  );
}

function Painel({ dados }: { dados: Overview }) {
  const { totais } = dados;
  const maxDia = Math.max(1, ...dados.serie_diaria.map((d) => d.consultas));

  return (
    <div className="space-y-6">
      {!dados.amostra_suficiente ? (
        <p className="rounded-md border border-status-warning/40 bg-status-warning/5 px-3 py-2 text-xs">
          Amostra de {totais.consultas} {totais.consultas === 1 ? "consulta" : "consultas"} no
          periodo — abaixo de {dados.amostra_minima}. Contagens sao exibidas; taxas ficam
          ocultas ate haver volume suficiente para significar algo.
        </p>
      ) : null}

      <section aria-label="Resumo" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Indicador
          rotulo="Consultas"
          valor={String(totais.consultas)}
          detalhe={`${dados.documentos_ativos} documentos · ${dados.chunks_indexados} trechos indexados`}
        />
        <Indicador
          rotulo="Taxa de resposta"
          valor={pct(dados.taxa_sucesso)}
          detalhe={`${totais.sucesso} respondidas · ${totais.sem_evidencia} sem evidencia · ${totais.falhas} falhas`}
          titulo="Consultas respondidas com citacao sobre o total do periodo"
        />
        <Indicador
          rotulo="Confianca media"
          valor={pct(dados.confianca_media)}
          detalhe="Calculada a partir do retrieval e das citacoes validas"
        />
        <Indicador
          rotulo="Latencia p95"
          valor={formatarMs(dados.latencia.p95_ms)}
          detalhe={`p50 ${formatarMs(dados.latencia.p50_ms)} · busca ${formatarMs(dados.latencia.retrieval_medio_ms)} · geracao ${formatarMs(dados.latencia.generation_medio_ms)}`}
        />
      </section>

      <div className="grid gap-6 lg:grid-cols-5">
        <section aria-label="Volume diario" className="rounded-lg border border-border lg:col-span-3">
          <div className="border-b border-border px-4 py-2.5">
            <h2 className="text-sm font-medium">Consultas por dia</h2>
          </div>
          <div className="px-4 py-4">
            {totais.consultas === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Nenhuma consulta no periodo.
              </p>
            ) : (
              <div
                className="flex h-40 items-end gap-px"
                role="img"
                aria-label={`Consultas por dia nos ultimos ${dados.dias} dias`}
              >
                {dados.serie_diaria.map((dia) => {
                  const altura = (dia.consultas / maxDia) * 100;
                  const lacunas = dia.consultas ? (dia.sem_evidencia / dia.consultas) * 100 : 0;
                  return (
                    <div
                      key={dia.dia}
                      className="group relative flex flex-1 flex-col justify-end"
                      style={{ height: "100%" }}
                      title={`${dia.dia}: ${dia.consultas} consultas, ${dia.sem_evidencia} sem evidencia`}
                    >
                      <div
                        className="relative w-full rounded-t-sm bg-chart-1/70"
                        style={{ height: `${altura}%`, minHeight: dia.consultas ? 2 : 0 }}
                      >
                        <div
                          className="absolute inset-x-0 bottom-0 rounded-t-sm bg-status-warning/80"
                          style={{ height: `${lacunas}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            <div className="mt-2 flex items-center gap-4 text-[0.6875rem] text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className="size-2 rounded-sm bg-chart-1/70" /> consultas
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className="size-2 rounded-sm bg-status-warning/80" /> sem evidencia
              </span>
            </div>
          </div>
        </section>

        <section aria-label="Feedback" className="rounded-lg border border-border lg:col-span-2">
          <div className="border-b border-border px-4 py-2.5">
            <h2 className="text-sm font-medium">Avaliacoes</h2>
          </div>
          <div className="space-y-3 px-4 py-4 text-sm">
            <div className="flex items-baseline justify-between">
              <span className="text-muted-foreground">Avaliacoes positivas</span>
              <span className="font-mono tabular-nums">
                {pct(dados.feedback.taxa_positiva)}{" "}
                <span className="text-xs text-muted-foreground">
                  ({dados.feedback.positivos}/{dados.feedback.total})
                </span>
              </span>
            </div>
            {dados.feedback.motivos.length > 0 ? (
              <div>
                <p className="mb-1.5 text-xs uppercase tracking-[0.12em] text-muted-foreground">
                  Motivos das negativas
                </p>
                <ul className="space-y-1">
                  {dados.feedback.motivos.map((m) => (
                    <li key={m.reason} className="flex justify-between">
                      <span>{MOTIVOS[m.reason as FeedbackReason] ?? m.reason}</span>
                      <span className="font-mono tabular-nums">{m.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Nenhuma avaliacao negativa com motivo no periodo.
              </p>
            )}
          </div>
        </section>
      </div>

      <section aria-label="Lacunas do acervo" className="rounded-lg border border-border">
        <div className="border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-medium">O que o acervo nao respondeu</h2>
          <p className="text-xs text-muted-foreground">
            Perguntas recusadas por falta de evidencia, agrupadas por semelhanca. Cada
            grupo e um documento que provavelmente falta.
          </p>
        </div>
        {dados.lacunas.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-muted-foreground">
            Nenhuma lacuna registrada no periodo.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {dados.lacunas.slice(0, 15).map((grupo) => (
              <li key={grupo.query_ids[0]} className="flex items-start gap-4 px-4 py-3">
                <span
                  className="mt-0.5 inline-flex h-6 min-w-8 shrink-0 items-center justify-center rounded bg-accent px-1.5 font-mono text-xs font-medium tabular-nums"
                  title="Ocorrencias no periodo"
                >
                  {grupo.ocorrencias}×
                </span>
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/history/${grupo.query_ids[0]}`}
                    className="block text-sm font-medium hover:underline"
                  >
                    {grupo.representante}
                  </Link>
                  {grupo.exemplos.length > 0 ? (
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      Tambem: {grupo.exemplos.join(" · ")}
                    </p>
                  ) : null}
                </div>
                <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">
                  {formatarData(grupo.ultima_em)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Ranking
          titulo="Documentos mais utilizados"
          vazio="Nenhuma citacao no periodo."
          linhas={dados.documentos_mais_citados.map((d) => ({
            chave: d.document_id,
            principal: d.title,
            secundario: `${d.consultas} ${d.consultas === 1 ? "consulta" : "consultas"}`,
            valor: d.citacoes,
          }))}
        />
        <Ranking
          titulo="Secoes mais citadas"
          vazio="Nenhuma citacao no periodo."
          linhas={dados.secoes_mais_citadas.map((s, i) => ({
            chave: `${s.document_id}-${i}`,
            principal: s.section_path ?? "Sem secao",
            secundario: s.document_title,
            valor: s.citacoes,
          }))}
        />
      </div>
    </div>
  );
}

function Indicador({
  rotulo,
  valor,
  detalhe,
  titulo,
}: {
  rotulo: string;
  valor: string;
  detalhe: string;
  titulo?: string;
}) {
  return (
    <div className="rounded-lg border border-border px-4 py-3" title={titulo}>
      <p className="text-xs uppercase tracking-[0.12em] text-muted-foreground">{rotulo}</p>
      <p className="mt-1 font-mono text-2xl font-semibold tabular-nums">{valor}</p>
      <p className="mt-1 truncate text-xs text-muted-foreground" title={detalhe}>
        {detalhe}
      </p>
    </div>
  );
}

function Ranking({
  titulo,
  vazio,
  linhas,
}: {
  titulo: string;
  vazio: string;
  linhas: { chave: string; principal: string; secundario: string; valor: number }[];
}) {
  const maximo = Math.max(1, ...linhas.map((l) => l.valor));
  return (
    <section aria-label={titulo} className="rounded-lg border border-border">
      <div className="border-b border-border px-4 py-2.5">
        <h2 className="text-sm font-medium">{titulo}</h2>
      </div>
      {linhas.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-muted-foreground">{vazio}</p>
      ) : (
        <ol className="divide-y divide-border">
          {linhas.map((linha) => (
            <li key={linha.chave} className="px-4 py-2.5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 flex-1 truncate text-sm" title={linha.principal}>
                  {linha.principal}
                </span>
                <span className="font-mono text-sm tabular-nums">{linha.valor}</span>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <div className="h-1 flex-1 rounded bg-muted">
                  <div
                    className="h-1 rounded bg-chart-2/80"
                    style={{ width: `${(linha.valor / maximo) * 100}%` }}
                  />
                </div>
                <span className="w-28 truncate text-right text-[0.6875rem] text-muted-foreground">
                  {linha.secundario}
                </span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
