"""Extracao de PDF.

O PDF nao tem estrutura semantica: nao existe "isto e um titulo". Tudo o que se pode
recuperar sao linhas com posicao. A hierarquia sai depois, da numeracao — ver
`normalizer.py`.

O numero da pagina e preservado porque e o que permite ao analista localizar o trecho
no documento original ao abrir a fonte de uma resposta.
"""

from __future__ import annotations

from io import BytesIO

import structlog

from app.modules.ingestion.extractors.base import (
    Bloco,
    ExtractionError,
    NoTextLayerError,
    TextoExtraido,
)

logger = structlog.get_logger(__name__)

# Abaixo disso o PDF e tratado como digitalizado. Um PDF de texto real passa folgado;
# um escaneado devolve pouquissimos caracteres — lixo de metadado, no maximo.
_MINIMO_CARACTERES = 100


class PdfExtractor:
    def extrair(self, conteudo: bytes) -> TextoExtraido:
        from pypdf import PdfReader

        # PyPdfError e a base de toda excecao da biblioteca.
        from pypdf.errors import PyPdfError

        try:
            leitor = PdfReader(BytesIO(conteudo))
        except (PyPdfError, ValueError, OSError) as exc:
            raise ExtractionError(f"PDF ilegivel: {exc}") from exc

        if leitor.is_encrypted:
            # Decriptar com senha vazia cobre o caso comum de PDF "protegido" apenas
            # contra edicao, que e legivel sem senha.
            try:
                leitor.decrypt("")
            except Exception as exc:
                raise ExtractionError(
                    "O PDF esta protegido por senha. Envie uma versao sem protecao."
                ) from exc

        blocos: list[Bloco] = []
        total = 0

        for indice, pagina in enumerate(leitor.pages, start=1):
            try:
                texto = pagina.extract_text() or ""
            except Exception as exc:
                # Uma pagina corrompida nao invalida o documento inteiro, mas precisa
                # aparecer no log: um PDF com metade das paginas ilegiveis produziria
                # um documento indexado pela metade sem nenhum sinal disso.
                logger.warning(
                    "pdf_page_extraction_failed",
                    page=indice,
                    error_type=type(exc).__name__,
                )
                continue

            total += len(texto.strip())
            # Uma linha por bloco. O agrupamento em paragrafos acontece na
            # normalizacao, que tem contexto das paginas vizinhas para distinguir
            # cabecalho repetido de conteudo.
            blocos.extend(
                Bloco(texto=linha.strip(), pagina=indice)
                for linha in texto.split("\n")
                if linha.strip()
            )

        if total < _MINIMO_CARACTERES:
            raise NoTextLayerError

        metadados: dict[str, str] = {}
        if leitor.metadata:
            for chave, bruta in (("title", "/Title"), ("author", "/Author")):
                if valor := leitor.metadata.get(bruta):
                    metadados[chave] = str(valor)

        return TextoExtraido(blocos=blocos, total_paginas=len(leitor.pages), metadados=metadados)
