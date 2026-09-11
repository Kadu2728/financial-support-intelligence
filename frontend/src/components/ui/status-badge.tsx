import { cn } from "@/lib/utils";
import { ESTADO, type DocumentStatus } from "@/features/documents/types";

/**
 * Indicador de estado.
 *
 * Ponto e rotulo, nunca so a cor: daltonismo afeta cerca de 8% dos homens, e um
 * estado que so existe como cor e invisivel para eles. O `title` traz a explicacao
 * completa sem ocupar espaco na tabela.
 */
export function StatusBadge({ status }: { status: DocumentStatus }) {
  const { rotulo, cor, descricao } = ESTADO[status];

  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm" title={descricao}>
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", cor)} />
      {rotulo}
    </span>
  );
}
