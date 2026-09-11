# Acervo de demonstração

> **Material fictício.** O "Banco Exemplo S.A." não existe. Prazos, valores, códigos de
> transação e procedimentos foram inventados para demonstrar o sistema e **não constituem
> orientação real** sobre produtos ou serviços financeiros.
>
> Os documentos citam normas reais pelo número — como todo procedimento interno faz — mas
> o texto é sempre procedimento interno fictício, nunca o conteúdo da norma citada.

## Por que um acervo sintético

O pipeline de RAG não pode ser avaliado com documentos genéricos. O `section_path` que vira
a citação exibida depende de hierarquia real; a perna lexical da busca híbrida só é exercitada
por códigos e valores exatos; e o gate de evidência só é calibrável com perguntas que
sabidamente não têm resposta.

Cada característica do acervo existe por um motivo:

| Característica | O que exercita |
|---|---|
| Hierarquia numerada (`3`, `3.1`, `3.2`) | Detecção de seção no chunking — sem ela não há `section_path` |
| Códigos e valores exatos (`COD-2041`, `R$ 5.000,00`, `80 dias`) | Perna lexical, onde embeddings falham |
| Quatro formatos (PDF, DOCX, MD, TXT) | Os quatro extractors, cada um com estrutura diferente |
| Cabeçalho e rodapé repetidos nos PDFs | Normalização — esse texto não pode entrar nos chunks |
| Acentuação correta | Stemmer `portuguese` do PostgreSQL |
| Vocabulário repetido entre documentos | Ambiguidade real: recuperar a seção certa exige mais que casar palavras |
| Referências cruzadas (`ver POL-PLD-004, seção 4`) | Perguntas cuja resposta vive em dois documentos |

## Conteúdo

| Arquivo | Formato | Código | Categoria |
|---|---|---|---|
| `manual-cadastro-pessoa-fisica.pdf` | PDF | MAN-CAD-001 | Cadastro |
| `procedimento-operacional-pix.pdf` | PDF | PRO-PIX-007 | Pagamentos |
| `politica-seguranca-no-atendimento.pdf` | PDF | POL-SEG-009 | Segurança |
| `politica-prevencao-lavagem-dinheiro.docx` | DOCX | POL-PLD-004 | Compliance |
| `manual-atendimento-e-prazos.docx` | DOCX | MAN-ATE-002 | Atendimento |
| `guia-contestacao-transacoes.md` | Markdown | GUI-CON-011 | Atendimento |
| `procedimento-encerramento-conta.md` | Markdown | PRO-ENC-002 | Cadastro |
| `glossario-termos-e-siglas.txt` | Texto | GLO-REF-001 | Referência |

Cerca de 100 KB, 61 seções, 50 delas detectáveis por numeração no texto extraído.

## Conjunto de avaliação

[`perguntas-avaliacao.json`](./perguntas-avaliacao.json) traz 20 perguntas em quatro classes,
com as seções que deveriam ser recuperadas em cada uma. É a base da calibração da Fase 6:
os limiares do gate de evidência e a comparação entre `semantic`, `lexical` e `hybrid` saem
daí.

As cinco perguntas da classe `fora_do_acervo` são as mais importantes. A última é
deliberadamente difícil: pergunta por abertura de conta **PJ**, e o acervo fala de abertura
de conta e menciona CNPJ — a atração semântica é forte, mas a resposta não existe. Se o
sistema responder essa, o gate de evidência está frouxo.

## Regenerando

Os arquivos são versionados, então não é preciso gerá-los para rodar o projeto. Para alterar
o conteúdo, edite [`scripts/acervo_conteudo.py`](../scripts/acervo_conteudo.py) e rode:

```bash
cd backend && pip install -e ".[demo]" && .venv/Scripts/python ../scripts/gerar_acervo.py
```
