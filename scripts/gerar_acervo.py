"""Gera o acervo sintetico de demonstracao.

    cd backend && .venv/Scripts/python ../scripts/gerar_acervo.py

Os arquivos gerados ficam versionados em `demo/acervo/`, entao rodar este script so e
necessario ao alterar o conteudo em `acervo_conteudo.py`.

Cada formato e renderizado com a estrutura que o extrator da Fase 5 vai encontrar no
mundo real: PDF com cabecalho e rodape repetidos por pagina (que a normalizacao precisa
remover), DOCX com estilos de titulo, Markdown com `#` e texto puro com numeracao. Um
acervo inteiro em um so formato nao exercitaria o pipeline.

Requer o extra `demo`:  pip install -e ".[demo]"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from acervo_conteudo import ACERVO, AVISO, INSTITUICAO, Documento, Secao  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "demo" / "acervo"


def nivel(secao: Secao) -> int:
    """Profundidade pela numeracao: "3" e nivel 1, "3.2" e nivel 2."""
    return secao.numero.count(".") + 1


# --- PDF -------------------------------------------------------------------


def gerar_pdf(doc: Documento, destino: Path) -> None:
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    estilos = getSampleStyleSheet()
    corpo = ParagraphStyle(
        "corpo",
        parent=estilos["BodyText"],
        fontSize=10,
        leading=15,
        alignment=TA_JUSTIFY,
        spaceAfter=8,
    )
    titulo_secao = [
        ParagraphStyle("h1", parent=estilos["Heading1"], fontSize=13, spaceBefore=16, spaceAfter=6),
        ParagraphStyle("h2", parent=estilos["Heading2"], fontSize=11, spaceBefore=12, spaceAfter=4),
        ParagraphStyle("h3", parent=estilos["Heading3"], fontSize=10, spaceBefore=10, spaceAfter=4),
    ]

    def cabecalho_rodape(canvas, documento) -> None:  # noqa: ANN001
        """Cabecalho e rodape repetidos em toda pagina.

        Sao exatamente o ruido que a normalizacao da Fase 5 precisa detectar e remover:
        sem isso, o texto do rodape entra em cada chunk e polui os embeddings.
        """
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(2 * cm, A4[1] - 1.2 * cm, f"{INSTITUICAO} — {doc.titulo}")
        canvas.drawRightString(A4[0] - 2 * cm, A4[1] - 1.2 * cm, f"{doc.codigo} v{doc.versao}")
        canvas.line(2 * cm, A4[1] - 1.35 * cm, A4[0] - 2 * cm, A4[1] - 1.35 * cm)
        canvas.drawString(2 * cm, 1.2 * cm, "Documento interno — uso restrito")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Pagina {documento.page}")
        canvas.restoreState()

    fluxo: list[object] = [
        Paragraph(doc.titulo, estilos["Title"]),
        Paragraph(
            f"{INSTITUICAO} · {doc.codigo} · Versao {doc.versao}",
            ParagraphStyle("sub", parent=corpo, fontSize=9, textColor="#555555"),
        ),
        Spacer(1, 6),
        Paragraph(
            f"<i>{AVISO}</i>",
            ParagraphStyle("aviso", parent=corpo, fontSize=8, textColor="#777777"),
        ),
        PageBreak(),
    ]

    for secao in doc.secoes:
        estilo = titulo_secao[min(nivel(secao), 3) - 1]
        fluxo.append(Paragraph(f"{secao.numero} {secao.titulo}", estilo))
        fluxo.extend(Paragraph(texto, corpo) for texto in secao.paragrafos)

    SimpleDocTemplate(
        str(destino),
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        title=doc.titulo,
        author=INSTITUICAO,
    ).build(fluxo, onFirstPage=cabecalho_rodape, onLaterPages=cabecalho_rodape)


# --- DOCX ------------------------------------------------------------------


def gerar_docx(doc: Documento, destino: Path) -> None:
    from docx import Document as Docx
    from docx.shared import Pt

    arquivo = Docx()
    arquivo.core_properties.title = doc.titulo
    arquivo.core_properties.author = INSTITUICAO

    arquivo.add_heading(doc.titulo, level=0)
    sub = arquivo.add_paragraph(f"{INSTITUICAO} · {doc.codigo} · Versao {doc.versao}")
    sub.runs[0].font.size = Pt(9)
    aviso = arquivo.add_paragraph(AVISO)
    aviso.runs[0].italic = True
    aviso.runs[0].font.size = Pt(8)

    for secao in doc.secoes:
        # Estilos de titulo reais, nao negrito manual: e assim que um documento
        # corporativo vem, e o extrator pode usar isso para inferir hierarquia.
        arquivo.add_heading(f"{secao.numero} {secao.titulo}", level=min(nivel(secao), 4))
        for texto in secao.paragrafos:
            arquivo.add_paragraph(texto)

    arquivo.save(str(destino))


# --- Markdown e texto ------------------------------------------------------


def gerar_md(doc: Documento, destino: Path) -> None:
    linhas = [
        f"# {doc.titulo}",
        "",
        f"> {INSTITUICAO} · `{doc.codigo}` · Versao {doc.versao}",
        f"> _{AVISO}_",
        "",
    ]
    for secao in doc.secoes:
        linhas += ["#" * min(nivel(secao) + 1, 6) + f" {secao.numero} {secao.titulo}", ""]
        for texto in secao.paragrafos:
            linhas += [texto, ""]
    destino.write_text("\n".join(linhas), encoding="utf-8")


def gerar_txt(doc: Documento, destino: Path) -> None:
    largura = 78
    linhas = [
        doc.titulo.upper(),
        "=" * largura,
        f"{INSTITUICAO} | {doc.codigo} | Versao {doc.versao}",
        "",
        AVISO,
        "=" * largura,
        "",
    ]
    for secao in doc.secoes:
        # Sem marcacao nenhuma: a hierarquia existe apenas na numeracao, que e o caso
        # mais dificil para o detector de secoes.
        linhas += [f"{secao.numero} {secao.titulo}", "-" * largura]
        for texto in secao.paragrafos:
            linhas += [texto, ""]
    destino.write_text("\n".join(linhas), encoding="utf-8")


GERADORES = {"pdf": gerar_pdf, "docx": gerar_docx, "md": gerar_md, "txt": gerar_txt}


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)

    print(f"Gerando {len(ACERVO)} documentos em {DESTINO.relative_to(RAIZ)}\n")
    for doc in ACERVO:
        caminho = DESTINO / doc.arquivo
        GERADORES[doc.formato](doc, caminho)
        tamanho = caminho.stat().st_size
        subsecoes = sum(1 for s in doc.secoes if nivel(s) > 1)
        print(
            f"  {doc.formato.upper():5} {doc.arquivo:45} "
            f"{tamanho / 1024:6.1f} KB  {len(doc.secoes):2} secoes ({subsecoes} sub)"
        )

    print(f"\nTotal: {sum((DESTINO / d.arquivo).stat().st_size for d in ACERVO) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
