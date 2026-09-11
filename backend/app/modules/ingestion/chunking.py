"""Divisao do documento normalizado em chunks.

**Structure-aware: um chunk nunca atravessa fronteira de secao.** Essa e a regra que
sustenta a citacao exibida. Se um chunk comecasse na secao 3.2 e terminasse na 3.3, o
`section_path` dele seria uma meia-verdade, e o analista clicaria na fonte para conferir
um trecho que fala de outra coisa.

Secoes maiores que o limite sao divididas por janela deslizante DENTRO da secao, com
sobreposicao. Todos os pedacos herdam o mesmo `section_path`.

Parametros e justificativas em docs/rag-design.md §2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.ingestion.normalizer import DocumentoNormalizado, Secao

# ~512 tokens no alvo, ~800 no maximo (docs/rag-design.md). Convertidos para caracteres
# pela razao medida no acervo — ver `tokens.py`.
CHUNK_ALVO_TOKENS = 512
CHUNK_MAXIMO_TOKENS = 800
CHUNK_MINIMO_TOKENS = 64
OVERLAP_PROPORCAO = 0.15

# Quebra preferencial em fim de frase; a segunda opcao e fim de linha.
_FIM_DE_FRASE = re.compile(r"(?<=[.!?;:])\s+")


@dataclass(frozen=True, slots=True)
class Chunk:
    """Unidade de recuperacao e de citacao.

    `inicio` e `fim` sao offsets no texto normalizado. Sao eles que permitem destacar o
    trecho exato dentro do documento quando o analista abre a fonte.
    """

    indice: int
    texto: str
    tokens: int
    inicio: int
    fim: int
    section_path: str | None
    section_label: str | None
    pagina: int | None


def dividir(
    documento: DocumentoNormalizado,
    *,
    alvo_tokens: int = CHUNK_ALVO_TOKENS,
    maximo_tokens: int = CHUNK_MAXIMO_TOKENS,
    minimo_tokens: int = CHUNK_MINIMO_TOKENS,
) -> list[Chunk]:
    from app.modules.ingestion.tokens import contar_tokens, tokens_para_caracteres

    if not documento.texto.strip():
        return []

    trechos = _trechos_por_secao(documento)
    chunks: list[Chunk] = []
    pendente: tuple[str, int, Secao | None] | None = None

    for texto, inicio, secao in trechos:
        tokens = contar_tokens(texto)

        # Secao curta demais para virar chunk proprio: acumula com a proxima. Um chunk
        # de 20 tokens polui o ranking — casa com quase qualquer consulta por ser
        # generico demais, sem responder nada.
        if tokens < minimo_tokens:
            if pendente is None:
                pendente = (texto, inicio, secao)
            else:
                _, inicio_anterior, secao_anterior = pendente
                # Refatia do texto original em vez de concatenar: preserva a separacao
                # entre os trechos e mantem os offsets validos.
                pendente = (
                    documento.texto[inicio_anterior : inicio + len(texto)],
                    inicio_anterior,
                    secao_anterior,
                )
            continue

        if pendente is not None:
            _, inicio_anterior, secao_anterior = pendente
            # Junta o acumulado a esta secao, preservando o texto original entre eles.
            texto = documento.texto[inicio_anterior : inicio + len(texto)]
            inicio, secao = inicio_anterior, secao_anterior or secao
            tokens = contar_tokens(texto)
            pendente = None

        if tokens <= maximo_tokens:
            chunks.append(_montar(len(chunks), texto, inicio, secao))
            continue

        # Secao grande: janela deslizante dentro dela.
        limite = tokens_para_caracteres(alvo_tokens)
        sobreposicao = int(limite * OVERLAP_PROPORCAO)
        for pedaco, deslocamento in _janelas(texto, limite, sobreposicao):
            chunks.append(_montar(len(chunks), pedaco, inicio + deslocamento, secao))

    if pendente is not None:
        texto, inicio, secao = pendente
        if chunks:
            # Sobra final curta: anexar ao ultimo chunk e melhor que criar um chunk
            # minusculo, desde que o resultado nao estoure o maximo.
            ultimo = chunks[-1]
            juntado = documento.texto[ultimo.inicio : inicio + len(texto)]
            if contar_tokens(juntado) <= maximo_tokens:
                chunks[-1] = _montar(
                    ultimo.indice,
                    juntado,
                    ultimo.inicio,
                    secao if ultimo.section_path is None else None,
                    herdar=ultimo,
                )
            else:
                chunks.append(_montar(len(chunks), texto, inicio, secao))
        else:
            chunks.append(_montar(0, texto, inicio, secao))

    return chunks


def _trechos_por_secao(
    documento: DocumentoNormalizado,
) -> list[tuple[str, int, Secao | None]]:
    """Fatia o texto nos limites das secoes.

    Sem secao detectada (documento sem numeracao nem titulos), devolve o texto inteiro
    como um trecho — a janela deslizante cuida do resto.
    """
    if not documento.secoes:
        return [(documento.texto, 0, None)]

    trechos: list[tuple[str, int, Secao | None]] = []

    # Texto antes da primeira secao: capa, sumario, introducao sem titulo.
    primeira = documento.secoes[0]
    if primeira.inicio > 0:
        preambulo = documento.texto[: primeira.inicio].strip()
        if preambulo:
            trechos.append((preambulo, 0, None))

    for secao in documento.secoes:
        bruto = documento.texto[secao.inicio : secao.fim]
        texto = bruto.strip()
        if texto:
            # `strip` desloca o inicio; sem corrigir, os offsets apontariam para o
            # espaco em branco anterior ao conteudo.
            trechos.append((texto, secao.inicio + (len(bruto) - len(bruto.lstrip())), secao))

    return trechos


def _janelas(texto: str, limite: int, sobreposicao: int) -> list[tuple[str, int]]:
    """Divide em janelas de ~`limite` caracteres, quebrando em fim de frase.

    A sobreposicao existe para que um procedimento partido ao meio ainda apareca
    inteiro em algum chunk. Sem ela, uma pergunta sobre o trecho da emenda nao
    recuperaria nem a metade anterior nem a posterior de forma util.
    """
    if len(texto) <= limite:
        return [(texto, 0)]

    janelas: list[tuple[str, int]] = []
    inicio = 0

    while inicio < len(texto):
        fim = min(inicio + limite, len(texto))

        if fim < len(texto):
            # Recua ate o ultimo fim de frase dentro da janela, para nao cortar no meio
            # de uma sentenca. Procura so no ultimo terco: recuar demais produziria
            # chunks muito menores que o alvo.
            corte = _ultimo_corte(texto, inicio + (limite * 2 // 3), fim)
            if corte > inicio:
                fim = corte

        pedaco = texto[inicio:fim].strip()
        if pedaco:
            janelas.append(
                (pedaco, inicio + (len(texto[inicio:fim]) - len(texto[inicio:fim].lstrip())))
            )

        if fim >= len(texto):
            break
        inicio = max(fim - sobreposicao, inicio + 1)

    return janelas


def _ultimo_corte(texto: str, desde: int, ate: int) -> int:
    posicoes = [m.start() for m in _FIM_DE_FRASE.finditer(texto, desde, ate)]
    if posicoes:
        return posicoes[-1] + 1
    quebra = texto.rfind("\n", desde, ate)
    return quebra + 1 if quebra > desde else ate


def _montar(
    indice: int,
    texto: str,
    inicio: int,
    secao: Secao | None,
    *,
    herdar: Chunk | None = None,
) -> Chunk:
    from app.modules.ingestion.tokens import contar_tokens

    return Chunk(
        indice=indice,
        texto=texto,
        tokens=contar_tokens(texto),
        inicio=inicio,
        fim=inicio + len(texto),
        section_path=herdar.section_path if herdar else (secao.caminho if secao else None),
        section_label=herdar.section_label if herdar else (secao.numero if secao else None),
        pagina=herdar.pagina if herdar else (secao.pagina if secao else None),
    )
