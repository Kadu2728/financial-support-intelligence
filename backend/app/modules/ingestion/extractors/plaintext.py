"""Extracao de Markdown e texto puro.

Markdown declara titulos com `#`, e o nivel sai da contagem de cerquilhas. Texto puro
nao declara nada: a hierarquia existe apenas na numeracao, e e o caso mais dificil para
o detector de secoes.
"""

from __future__ import annotations

import re

from app.modules.ingestion.extractors.base import (
    Bloco,
    ExtractionError,
    TextoExtraido,
    TipoBloco,
)

_ATX = re.compile(r"^(#{1,6})\s+(.*)$")
_SETEXT_H1 = re.compile(r"^={3,}\s*$")
_SETEXT_H2 = re.compile(r"^-{3,}\s*$")
_MARCADOR_LISTA = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_DECORATIVA = re.compile(r"^[=\-_*~]{3,}$")


def _decodificar(conteudo: bytes) -> str:
    try:
        return conteudo.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError(
            "O arquivo nao esta em UTF-8. Salve-o nessa codificacao e reenvie."
        ) from exc


class MarkdownExtractor:
    def extrair(self, conteudo: bytes) -> TextoExtraido:
        linhas = _decodificar(conteudo).split("\n")
        blocos: list[Bloco] = []
        paragrafo: list[str] = []

        def fechar() -> None:
            if paragrafo:
                blocos.append(Bloco(texto=" ".join(paragrafo).strip()))
                paragrafo.clear()

        indice = 0
        while indice < len(linhas):
            crua = linhas[indice].rstrip()
            despida = crua.strip()
            indice += 1

            if not despida:
                fechar()
                continue

            if achado := _ATX.match(crua):
                fechar()
                blocos.append(
                    Bloco(
                        texto=achado.group(2).strip().rstrip("#").strip(),
                        tipo=TipoBloco.TITULO,
                        nivel=len(achado.group(1)),
                    )
                )
                continue

            # Titulo setext: o sublinhado vem DEPOIS do texto. Como a linha seguinte
            # decide o tipo da atual, e preciso olhar a frente antes de acumular.
            proxima = linhas[indice].rstrip() if indice < len(linhas) else ""
            if not paragrafo and (_SETEXT_H1.match(proxima) or _SETEXT_H2.match(proxima)):
                fechar()
                blocos.append(
                    Bloco(
                        texto=despida,
                        tipo=TipoBloco.TITULO,
                        nivel=1 if _SETEXT_H1.match(proxima) else 2,
                    )
                )
                indice += 1  # consome o sublinhado
                continue

            if _DECORATIVA.match(despida):
                fechar()
                continue

            # Marcadores de lista e citacao nao acrescentam significado e virariam
            # ruido no embedding.
            limpa = _MARCADOR_LISTA.sub("", despida)
            paragrafo.append(re.sub(r"^>\s?", "", limpa))

        fechar()
        return TextoExtraido(blocos=blocos)


class PlainTextExtractor:
    def extrair(self, conteudo: bytes) -> TextoExtraido:
        blocos: list[Bloco] = []
        paragrafo: list[str] = []

        def fechar() -> None:
            if paragrafo:
                blocos.append(Bloco(texto=" ".join(paragrafo).strip()))
                paragrafo.clear()

        for linha in _decodificar(conteudo).split("\n"):
            despida = linha.strip()
            if not despida or _DECORATIVA.match(despida):
                # Linhas decorativas separam secoes em texto puro e nao sao conteudo.
                fechar()
                continue
            paragrafo.append(despida)

        fechar()
        return TextoExtraido(blocos=blocos)
