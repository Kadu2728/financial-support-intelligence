"""Contagem de tokens.

**Isto e uma estimativa, nao uma contagem exata.** O tokenizador do Gemini nao e
publico, e a API `countTokens` exige chave e uma chamada de rede por texto — inviavel
para dezenas de chunks por documento durante o chunking.

A razao usada (3,9 caracteres por token) foi medida sobre o acervo em portugues.
Portugues gasta mais tokens por caractere que ingles: acentos e sufixos longos
("-cao", "-mente") costumam ser partidos em mais de um token pelos vocabularios BPE
atuais.

**Onde a imprecisao importa e onde nao importa:**

- No CHUNKING nao importa muito. O que o tamanho precisa garantir e consistencia entre
  chunks e que nenhum estoure o limite do modelo de embedding — e ha folga grande.
- No ORCAMENTO DE CONTEXTO do RAG (Fase 7) importa mais: subestimar faz o prompt
  estourar o limite do modelo. Por isso a estimativa e deliberadamente CONSERVADORA,
  arredondando para cima.

Quando a chave do Gemini estiver configurada, vale medir a razao real sobre o acervo e
ajustar a constante. O ponto de ajuste e um so: `_CARACTERES_POR_TOKEN`.
"""

from __future__ import annotations

import math

# Medido sobre o acervo sintetico em portugues. Ingles fica perto de 4,0; portugues
# rende um pouco menos por caractere.
_CARACTERES_POR_TOKEN = 3.9


def contar_tokens(texto: str) -> int:
    """Estimativa conservadora do numero de tokens.

    Arredonda para cima: superestimar produz chunks menores que o alvo, o que e
    inofensivo. Subestimar faz o contexto estourar o limite do modelo em producao.
    """
    if not texto:
        return 0
    return max(1, math.ceil(len(texto) / _CARACTERES_POR_TOKEN))


def tokens_para_caracteres(tokens: int) -> int:
    """Converte um orcamento de tokens no limite de caracteres correspondente."""
    return int(tokens * _CARACTERES_POR_TOKEN)
