"""Avaliacao do retrieval contra o conjunto de demo/perguntas-avaliacao.json.

Roda os tres modos (semantic, lexical, hybrid) sobre o acervo INDEXADO no banco
configurado em backend/.env e imprime, por modo:

- recall@K   : fracao das perguntas em que alguma fonte esperada aparece no top-K
- MRR        : media de 1/posicao da primeira fonte esperada
- gate       : para `fora_do_acervo`, taxa de recusa correta; para as demais, taxa
               de recusa indevida (falso negativo do gate)

E a evidencia por tras de "busca hibrida e melhor" em docs/rag-design.md §10 e a
base para calibrar RAG_MIN_TOP_SCORE / RAG_MIN_SUPPORT_SCORE.

Uso (da raiz do repositorio, com o acervo ja indexado):

    backend/.venv/Scripts/python scripts/avaliar_busca.py [--top-k 8] [--json saida.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.core.config import get_settings
from app.db import registry as _registry  # noqa: F401
from app.db.session import create_engine, create_session_factory
from app.integrations.gemini.client import GeminiClient
from app.modules.rag.gate import avaliar_gate
from app.modules.search.repository import SearchRepository
from app.modules.search.service import Hit, SearchMode, SearchService

# Codigo do documento -> nome do arquivo enviado (demo/README.md).
ARQUIVO_POR_CODIGO = {
    "MAN-CAD-001": "manual-cadastro-pessoa-fisica.pdf",
    "PRO-PIX-007": "procedimento-operacional-pix.pdf",
    "POL-SEG-009": "politica-seguranca-no-atendimento.pdf",
    "POL-PLD-004": "politica-prevencao-lavagem-dinheiro.docx",
    "MAN-ATE-002": "manual-atendimento-e-prazos.docx",
    "GUI-CON-011": "guia-contestacao-transacoes.md",
    "PRO-ENC-002": "procedimento-encerramento-conta.md",
    "GLO-REF-001": "glossario-termos-e-siglas.txt",
}


@dataclass
class Linha:
    id: str
    classe: str
    modo: str
    posicao: int | None  # 1-based da primeira fonte esperada; None = nao apareceu
    top_similarity: float | None
    recusou: bool
    fontes_no_topk: list[str]


def _casa(hit: Hit, esperada: str, arquivo_por_version: dict[str, str]) -> bool:
    codigo, _, secao = esperada.partition(" ")
    arquivo = ARQUIVO_POR_CODIGO[codigo]
    if arquivo_por_version.get(str(hit.chunk.version_id)) != arquivo:
        return False
    if not secao:
        return True
    rotulo = (hit.chunk.section_label or "").strip()
    caminho = hit.chunk.section_path or ""
    # "3.1" casa a propria secao e as filhas ("3.1.2"); "3" casa "3", "3.1", "3.2"...
    return (
        rotulo == secao
        or rotulo.startswith(secao + ".")
        or f" {secao} " in f" {caminho} "
        or any(parte.strip().startswith(secao + " ") for parte in caminho.split(">"))
    )


async def main(top_k: int, saida_json: Path | None) -> int:
    from sqlalchemy import text

    settings = get_settings()
    if not settings.gemini_configured:
        print("GEMINI_API_KEY nao configurada em backend/.env.", file=sys.stderr)
        return 1

    conjunto = json.loads(
        (RAIZ / "demo" / "perguntas-avaliacao.json").read_text("utf-8")
    )
    perguntas = conjunto["perguntas"]

    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    gemini = GeminiClient(settings)
    linhas: list[Linha] = []

    try:
        async with sessions() as session:
            mapa = (
                await session.execute(
                    text(
                        "SELECT id::text, original_filename FROM document_versions "
                        "WHERE is_current"
                    )
                )
            ).all()
            arquivo_por_version = dict(mapa)
            if not arquivo_por_version:
                print(
                    "Nenhuma versao READY no banco. Rode `python -m app.cli process-queue`."
                )
                return 1

            servico = SearchService(
                settings=settings,
                repository=SearchRepository(session),
                embeddings=gemini,
            )

            for pergunta in perguntas:
                # Um embedding por pergunta, reaproveitado nos tres modos.
                vetor = await servico.embed_question(pergunta["pergunta"])
                for modo in SearchMode:
                    resultado = await servico.search(
                        pergunta["pergunta"], mode=modo, top_k=top_k, embedding=vetor
                    )
                    posicao = None
                    encontradas: list[str] = []
                    for indice, hit in enumerate(resultado.hits, start=1):
                        for esperada in pergunta["fontes_esperadas"]:
                            if _casa(hit, esperada, arquivo_por_version):
                                encontradas.append(esperada)
                                if posicao is None:
                                    posicao = indice
                    decisao = avaliar_gate(resultado.hits, settings)
                    linhas.append(
                        Linha(
                            id=pergunta["id"],
                            classe=pergunta["classe"],
                            modo=modo.value,
                            posicao=posicao,
                            top_similarity=resultado.top_similarity,
                            recusou=not decisao.aprovado,
                            fontes_no_topk=sorted(set(encontradas)),
                        )
                    )
    finally:
        await gemini.aclose()
        await engine.dispose()

    _relatorio(linhas, top_k)
    if saida_json:
        _gravar(saida_json, linhas)
    return 0


def _gravar(destino: Path, linhas: list[Linha]) -> None:
    destino.write_text(
        json.dumps([asdict(linha) for linha in linhas], ensure_ascii=False, indent=2),
        "utf-8",
    )
    print(f"\nDetalhe gravado em {destino}")


def _relatorio(linhas: list[Linha], top_k: int) -> None:
    recall_k = f"recall@{top_k}"
    print(
        f"\n{'modo':<10}{'classe':<16}{'n':>3}{recall_k:>11}{'MRR':>8}{'recusas':>10}"
    )
    print("-" * 58)
    for modo in SearchMode:
        for classe in ("literal", "parafrase", "multi_secao", "fora_do_acervo"):
            grupo = [
                linha
                for linha in linhas
                if linha.modo == modo.value and linha.classe == classe
            ]
            if not grupo:
                continue
            if classe == "fora_do_acervo":
                recusas = sum(linha.recusou for linha in grupo)
                print(
                    f"{modo.value:<10}{classe:<16}{len(grupo):>3}{'-':>11}{'-':>8}"
                    f"{recusas:>5}/{len(grupo):<4} (correto)"
                )
                continue
            recall = sum(linha.posicao is not None for linha in grupo) / len(grupo)
            mrr = sum(1 / linha.posicao for linha in grupo if linha.posicao) / len(
                grupo
            )
            recusas = sum(linha.recusou for linha in grupo)
            print(
                f"{modo.value:<10}{classe:<16}{len(grupo):>3}{recall:>11.2f}{mrr:>8.2f}"
                f"{recusas:>5}/{len(grupo):<4} (indevidas)"
            )
        print("-" * 58)

    print("\nSimilaridade do topo (hybrid) — insumo para os limiares do gate:")
    for classe in ("literal", "parafrase", "multi_secao", "fora_do_acervo"):
        valores = [
            linha.top_similarity
            for linha in linhas
            if linha.modo == "hybrid"
            and linha.classe == classe
            and linha.top_similarity is not None
        ]
        if valores:
            print(
                f"  {classe:<16} min={min(valores):.3f}  media={sum(valores) / len(valores):.3f}"
                f"  max={max(valores):.3f}"
            )

    faltantes = [
        linha
        for linha in linhas
        if linha.modo == "hybrid"
        and linha.classe != "fora_do_acervo"
        and linha.posicao is None
    ]
    if faltantes:
        print("\nHybrid nao encontrou (investigar):")
        for linha in faltantes:
            print(f"  {linha.id}  top_similarity={linha.top_similarity}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.top_k, args.json)))
