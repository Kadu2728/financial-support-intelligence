"""Gate de evidencia (ADR-0008, camada 1).

Decide, ANTES de chamar o modelo, se o retrieval trouxe base suficiente para uma
resposta. Se nao trouxe, a recusa e imediata e sem custo — e, mais importante, sem
dar ao modelo a chance de preencher a lacuna com algo plausivel.

Duas condicoes, ambas necessarias:

1. O melhor chunk tem similaridade >= `rag_min_top_score`. Abaixo disso, nem o
   melhor candidato fala do assunto.
2. Ao menos `rag_min_support_count` chunks tem similaridade >= `rag_min_support_score`.
   Um unico chunk parecido pode ser coincidencia de vocabulario; dois ou mais
   indicam que o acervo cobre o tema.

Os limiares vivem em configuracao e sao calibrados por scripts/avaliar_busca.py.
Funcao pura: recebe hits, devolve decisao. Testavel sem banco e sem modelo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.config import Settings
from app.modules.search.service import Hit


@dataclass(frozen=True, slots=True)
class DecisaoGate:
    aprovado: bool
    motivo: str | None
    top_similarity: float | None
    suporte: int

    @property
    def detalhes(self) -> dict[str, object]:
        return {
            "top_similarity": self.top_similarity,
            "support_count": self.suporte,
            "reason": self.motivo,
        }


def avaliar_gate(hits: Sequence[Hit], settings: Settings) -> DecisaoGate:
    similaridades = sorted((h.similarity for h in hits if h.similarity is not None), reverse=True)
    if not similaridades:
        return DecisaoGate(False, "sem_candidatos", None, 0)

    topo = similaridades[0]
    suporte = sum(1 for s in similaridades if s >= settings.rag_min_support_score)

    if topo < settings.rag_min_top_score:
        return DecisaoGate(False, "topo_abaixo_do_limiar", topo, suporte)
    if suporte < settings.rag_min_support_count:
        return DecisaoGate(False, "suporte_insuficiente", topo, suporte)
    return DecisaoGate(True, None, topo, suporte)
