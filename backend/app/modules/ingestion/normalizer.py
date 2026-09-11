"""Normalizacao do texto extraido.

Transforma blocos crus em um documento com hierarquia de secoes e offsets estaveis.
E a etapa que mais determina a qualidade final: chunk montado sobre texto sujo produz
embedding sujo, e nenhum ajuste de busca compensa isso depois.

Quatro problemas sao tratados, na ordem:

1. **Cabecalho e rodape repetidos** — presentes em toda pagina de PDF. Se entrarem nos
   chunks, o nome do documento e "Pagina 3" aparecem em cada embedding e aproximam
   artificialmente trechos que nada tem em comum.

2. **Linhas quebradas no meio da frase** — o PDF quebra por largura visual, nao por
   sentido. "acima de R$\\n5.000,00" precisa voltar a ser uma frase, senao o valor fica
   separado do simbolo e a busca literal por "R$ 5.000,00" falha.

3. **Hifenizacao de quebra de linha** — "atualiza-\\ncao" vira duas nao-palavras que o
   stemmer nao reconhece.

4. **Hierarquia de secoes** — o `section_path` que vira a citacao exibida. Vem do
   formato quando ele declara (DOCX, Markdown) e da numeracao quando nao declara
   (PDF, TXT).

Os offsets (`inicio`, `fim`) apontam para o texto NORMALIZADO, que e o mesmo gravado em
`document_chunks.content`. Normalizar depois de calcular offsets os invalidaria.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.modules.ingestion.extractors.base import Bloco, TextoExtraido, TipoBloco

# Numeracao de secao: "3", "3.2", "3.2.1", seguida do titulo. O titulo precisa comecar
# com maiuscula para nao capturar "3.2 do manual anterior" no meio de uma frase.
_NUMERADA = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})[.)]?\s+([A-ZÀ-Þ][^\n]{2,90})$")

# Titulo sem numeracao, em caixa alta. Comum em documentos antigos.
_CAIXA_ALTA = re.compile(r"^([A-ZÀ-Þ][A-ZÀ-Þ\s,\-]{4,70})$")

_HIFENIZACAO = re.compile(r"(\w)-\s*\n\s*(\w)")
# Todo espaco em branco menos a quebra de linha. Escrito como classe negada, e nao
# literal, porque \s em Unicode ja cobre NBSP e espacos tipograficos que PDFs usam —
# e assim nenhum caractere invisivel fica no codigo-fonte.
_ESPACOS = re.compile(r"[^\S\n]+")

# Numeros viram placeholder ao comparar linhas repetidas: "Pagina 1" e "Pagina 2"
# sao o MESMO rodape. Sem isso, todo rodape numerado escapa da deteccao.
_DIGITOS = re.compile(r"\d+")

# Uma linha so e cabecalho/rodape se repetir na maioria das paginas. Em documento de
# 2 paginas isso e fraco, entao o minimo de paginas evita falso positivo.
_LIMIAR_REPETICAO = 0.6

# Duas paginas ja bastam. O piso de duas ocorrencias (ver `minimo`, abaixo) faz com que
# um documento de duas paginas exija a linha em AMBAS — 100% de repeticao, criterio bem
# mais forte que os 60% pedidos num documento longo. Exigir tres paginas deixava passar
# o cabecalho de todo documento curto, que e boa parte de um acervo de procedimentos.
_MINIMO_PAGINAS = 2

# Quantas linhas de cada extremidade da pagina entram na busca por repeticao.
#
# Cinco, e nao tres: a ordem de extracao segue o stream do PDF, nao a posicao visual.
# O rodape costuma aparecer logo depois do cabecalho, no quarto ou quinto bloco — foi
# exatamente o que aconteceu com "Pagina N" no acervo. Alargar a janela e seguro porque
# o criterio real e a REPETICAO entre paginas: conteudo legitimo nao se repete identico
# em 60% delas.
_LINHAS_DE_BORDA = 5


@dataclass(frozen=True, slots=True)
class Secao:
    """Uma secao do documento, com o intervalo que ocupa no texto normalizado."""

    numero: str | None
    titulo: str
    caminho: str
    nivel: int
    inicio: int
    fim: int
    pagina: int | None = None

    @property
    def rotulo(self) -> str:
        return f"{self.numero} {self.titulo}" if self.numero else self.titulo


@dataclass(frozen=True, slots=True)
class DocumentoNormalizado:
    texto: str
    secoes: list[Secao]
    total_paginas: int | None = None
    linhas_removidas: list[str] = field(default_factory=list)

    def secao_em(self, posicao: int) -> Secao | None:
        """Secao que contem a posicao. Usado pelo chunker para herdar o caminho."""
        for secao in self.secoes:
            if secao.inicio <= posicao < secao.fim:
                return secao
        return None


def normalizar(extraido: TextoExtraido) -> DocumentoNormalizado:
    blocos = list(extraido.blocos)

    blocos, removidas = _remover_repetidos(blocos, extraido.total_paginas)
    blocos = _agrupar_em_paragrafos(blocos)

    partes: list[str] = []
    secoes_cruas: list[tuple[str | None, str, int, int, int | None]] = []
    posicao = 0

    for bloco in blocos:
        texto = _limpar(bloco.texto)
        if not texto:
            continue

        numero, titulo, nivel = _identificar_titulo(bloco, texto)
        if titulo is not None:
            secoes_cruas.append((numero, titulo, nivel, posicao, bloco.pagina))

        partes.append(texto)
        posicao += len(texto) + 2  # "\n\n" entre blocos

    texto_final = "\n\n".join(partes)
    return DocumentoNormalizado(
        texto=texto_final,
        secoes=_montar_hierarquia(secoes_cruas, len(texto_final)),
        total_paginas=extraido.total_paginas,
        linhas_removidas=removidas,
    )


# --- Etapa 1: cabecalho e rodape -------------------------------------------


def _remover_repetidos(
    blocos: list[Bloco], total_paginas: int | None
) -> tuple[list[Bloco], list[str]]:
    """Remove linhas que se repetem nas bordas da maioria das paginas.

    Considera apenas as primeiras e ultimas linhas de cada pagina: uma frase que
    aparece varias vezes no meio do texto e conteudo legitimo (uma definicao repetida,
    por exemplo), nao cabecalho.
    """
    if not total_paginas or total_paginas < _MINIMO_PAGINAS:
        return blocos, []

    por_pagina: dict[int, list[Bloco]] = {}
    for bloco in blocos:
        if bloco.pagina is not None:
            por_pagina.setdefault(bloco.pagina, []).append(bloco)

    # A contagem usa a forma com digitos mascarados, para que "Pagina 1" e "Pagina 2"
    # sejam reconhecidos como o mesmo rodape. O texto original e guardado so para o log.
    candidatas: Counter[str] = Counter()
    originais: dict[str, set[str]] = {}

    for linhas in por_pagina.values():
        bordas = {
            b.texto.strip()
            for b in linhas[:_LINHAS_DE_BORDA] + linhas[-_LINHAS_DE_BORDA:]
            if _parece_ornamento(b.texto.strip())
        }
        for linha in bordas:
            chave = _mascarar(linha)
            candidatas[chave] += 1
            originais.setdefault(chave, set()).add(linha)

    minimo = max(2, int(len(por_pagina) * _LIMIAR_REPETICAO))
    repetidas = {chave for chave, vezes in candidatas.items() if vezes >= minimo}

    if not repetidas:
        return blocos, []

    mantidos = [
        b
        for b in blocos
        if not (_parece_ornamento(b.texto.strip()) and _mascarar(b.texto.strip()) in repetidas)
    ]
    removidas = sorted(texto for chave in repetidas for texto in originais[chave])
    return mantidos, removidas


def _mascarar(linha: str) -> str:
    """Forma canonica de uma linha para comparacao entre paginas."""
    return _DIGITOS.sub("#", linha)


def _parece_ornamento(linha: str) -> bool:
    """Distingue cabecalho e rodape de conteudo, por forma e nao por posicao.

    Cabecalho e rodape sao FRAGMENTOS: "Banco Exemplo — Manual", "Pagina 3 de 12",
    "MAN-CAD-001 v4.2". Conteudo e frase, e frase termina com pontuacao final.

    Este criterio importa porque a posicao sozinha nao basta. A ordem de extracao segue
    o stream do PDF, nao a posicao visual, entao a janela de borda precisa ser generosa
    — e uma janela generosa alcanca conteudo. Sem esta checagem, uma pagina curta teria
    o proprio texto descartado como cabecalho.
    """
    if not linha:
        return False
    if linha.rstrip().endswith((".", "!", "?")):
        return False
    # Cabecalho e curto. Um fragmento longo que se repete tende a ser conteudo.
    return len(linha) < 120


# --- Etapa 2: reagrupamento em paragrafos ----------------------------------


def _agrupar_em_paragrafos(blocos: list[Bloco]) -> list[Bloco]:
    """Junta linhas que fazem parte da mesma frase.

    So se aplica a blocos de PDF (com pagina): DOCX, Markdown e TXT ja entregam
    paragrafos inteiros, e reagrupar ali juntaria paragrafos distintos.
    """
    resultado: list[Bloco] = []

    for bloco in blocos:
        if bloco.pagina is None or bloco.tipo is TipoBloco.TITULO:
            resultado.append(bloco)
            continue

        anterior = resultado[-1] if resultado else None
        if (
            anterior is not None
            and anterior.pagina is not None
            and anterior.tipo is not TipoBloco.TITULO
            and _continua_frase(anterior.texto, bloco.texto)
        ):
            resultado[-1] = Bloco(
                texto=f"{anterior.texto} {bloco.texto}",
                tipo=anterior.tipo,
                nivel=anterior.nivel,
                pagina=anterior.pagina,
            )
        else:
            resultado.append(bloco)

    return resultado


def _continua_frase(anterior: str, atual: str) -> bool:
    """Decide se `atual` e continuacao de `anterior`.

    A linha anterior terminar sem pontuacao final e o sinal mais forte: o PDF quebrou
    por largura, nao por fim de frase. Se `atual` comeca com numeracao de secao, e
    titulo novo e nunca continuacao — e o que impede "R$\\n5.000,00" de ser tratado
    como secao "5.000".
    """
    if not anterior or not atual:
        return False
    if _NUMERADA.match(atual):
        return False
    if anterior.rstrip().endswith((".", ":", ";", "!", "?")):
        return False
    # Minuscula, digito ou abertura de parenteses indicam meio de frase.
    return atual[0].islower() or atual[0].isdigit() or atual[0] in '(“"'


# --- Etapa 3: limpeza ------------------------------------------------------


def _limpar(texto: str) -> str:
    texto = _HIFENIZACAO.sub(r"\1\2", texto)
    texto = texto.replace("­", "")  # hifen condicional, invisivel e inutil aqui
    texto = _ESPACOS.sub(" ", texto)
    return texto.strip()


# --- Etapa 4: hierarquia ---------------------------------------------------


def _identificar_titulo(bloco: Bloco, texto: str) -> tuple[str | None, str | None, int]:
    """Devolve (numero, titulo, nivel). Titulo None significa que o bloco e corpo.

    A declaracao do formato tem prioridade sobre a heuristica: quando o DOCX diz
    "Heading 2", nao ha o que inferir.
    """
    if bloco.tipo is TipoBloco.TITULO:
        if achado := _NUMERADA.match(texto):
            numero = achado.group(1)
            # O nivel vem da numeracao, mais confiavel que o estilo: um documento pode
            # usar Heading 1 para "3.2" por descuido de formatacao.
            return numero, achado.group(2).strip(), numero.count(".") + 1
        return None, texto, bloco.nivel or 1

    if achado := _NUMERADA.match(texto):
        numero = achado.group(1)
        return numero, achado.group(2).strip(), numero.count(".") + 1

    if _CAIXA_ALTA.match(texto) and len(texto.split()) <= 10:
        return None, texto.strip(), 1

    return None, None, 0


def _montar_hierarquia(
    cruas: list[tuple[str | None, str, int, int, int | None]], fim_texto: int
) -> list[Secao]:
    """Monta o `section_path` acumulando os ancestrais de cada secao.

    O caminho e o que aparece na citacao: "3 Atualizacao cadastral > 3.2 Procedimento".
    Sem ele, a fonte exibida seria apenas o nome do documento — verdadeira, mas inutil
    para quem precisa conferir o trecho.
    """
    secoes: list[Secao] = []
    pilha: list[tuple[int, str]] = []  # (nivel, rotulo)

    for indice, (numero, titulo, nivel, inicio, pagina) in enumerate(cruas):
        while pilha and pilha[-1][0] >= nivel:
            pilha.pop()

        rotulo = f"{numero} {titulo}" if numero else titulo
        caminho = " > ".join([*(r for _, r in pilha), rotulo])
        pilha.append((nivel, rotulo))

        # A secao vai ate o inicio da proxima, seja qual for o nivel dela.
        fim = cruas[indice + 1][3] if indice + 1 < len(cruas) else fim_texto

        secoes.append(
            Secao(
                numero=numero,
                titulo=titulo,
                caminho=caminho,
                nivel=nivel,
                inicio=inicio,
                fim=fim,
                pagina=pagina,
            )
        )

    return secoes
