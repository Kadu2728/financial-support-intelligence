# ADR-0002 — Busca híbrida (pgvector + full-text) com fusão RRF

- **Status:** Aceito
- **Data:** 2026-09-09
- **Fase:** 0

## Contexto

O desenho inicial previa apenas busca vetorial via pgvector. Embeddings capturam semântica, mas são
notoriamente fracos em **correspondência literal**.

O corpus deste sistema é denso em tokens exatos: `PIX`, `CDB`, `LCI`, `Circular 3.978`, códigos de
produto, números de seção, siglas internas. Quando o analista pergunta *"qual o procedimento da
Circular 3.978"*, a busca vetorial tende a recuperar "procedimentos regulatórios" genéricos e perder
o documento específico — o token que mais importa é justamente o que o embedding dilui.

O caso inverso também existe: *"atualizar dados do cliente"* precisa recuperar "manutenção
cadastral", onde não há sobreposição léxica alguma. Busca lexical sozinha falha aqui.

As duas estratégias falham em situações complementares.

## Decisão

**Busca híbrida, inteiramente dentro do PostgreSQL:**

1. Perna semântica: `pgvector`, distância cosine, índice HNSW, top-30.
2. Perna lexical: `tsvector` com configuração `portuguese`, ranqueada por `ts_rank_cd`, índice GIN, top-30.
3. Fusão por **Reciprocal Rank Fusion**: `score(d) = Σ 1 / (k + rank_i(d))`, com `k = 60`.
4. Deduplicação por seção e corte no top-8.

A coluna `tsv` é `GENERATED ALWAYS AS (to_tsvector('portuguese', content)) STORED`. A variante de
dois argumentos de `to_tsvector` é `IMMUTABLE` (a de um argumento é apenas `STABLE`), o que a torna
válida em coluna gerada — detalhe que quebra a migration se ignorado.

### Por que RRF e não soma ponderada de scores

Cosine similarity vive em `[-1, 1]`; `ts_rank_cd` é ilimitado e depende do tamanho do documento. As
escalas são incomparáveis, e normalizá-las exigiria calibração empírica frágil que precisaria ser
refeita a cada mudança de corpus.

RRF opera apenas sobre **posições no ranking**, descartando as magnitudes. É livre de calibração,
robusto a mudanças de distribuição e é o padrão consolidado na literatura de recuperação de
informação. O `k = 60` é o valor canônico e amortece a influência das primeiras posições.

## Consequências

### Positivas

- Recall substancialmente melhor no corpus real, sem custo de infraestrutura adicional.
- PostgreSQL passa a ser peça central da arquitetura, não apenas persistência.
- As duas pernas são independentes e mensuráveis em isolamento — essencial para a calibração da
  Fase 6, que compara `semantic`, `lexical` e `hybrid` no mesmo conjunto de avaliação.
- O endpoint `/search` expõe os três modos, o que também serve de ferramenta de depuração.

### Negativas

- Duas queries por consulta em vez de uma. Ambas são indexadas e o custo somado permanece na casa de
  dezenas de milissegundos para o volume previsto.
- Índice GIN adicional aumenta o custo de escrita na ingestão — irrelevante, já que a escrita é
  assíncrona e em lote.
- A configuração `portuguese` do PostgreSQL usa stemmer Snowball, inferior a lematização real. É
  suficiente para o caso de uso e não justifica dependência externa.

## Alternativas consideradas

**Elasticsearch / OpenSearch.** Rejeitado: mais um serviço para operar, deployar e manter em sincronia
com o Postgres, para ganho marginal em um corpus desta escala. Introduziria consistência eventual
entre o registro do documento e seu índice de busca.

**Apenas vetorial.** Rejeitado pelo motivo central deste ADR: falha exatamente nas consultas por
código, sigla e referência normativa, que são frequentes no domínio.

**Apenas full-text.** Rejeitado: não resolve paráfrase, que é o modo natural de perguntar em
linguagem natural.

**Reranking com cross-encoder.** Adiado, não rejeitado. Melhoraria a precisão do top-8, mas adiciona
latência e outra dependência de modelo. Registrado como evolução em `architecture.md` §12.

## Revisão após medição (2026-09-11)

A avaliação da Fase 6 (`docs/rag-design.md` §10) contradisse parte do contexto acima: no acervo
de demonstração, a perna semântica sozinha alcançou recall 1.00 nas consultas literais — o
`gemini-embedding-001` representa bem códigos que aparecem literalmente no chunk. E a perna
lexical sobre a pergunta inteira **piorou** a híbrida (paráfrase: 0.83 → 0.33), porque o AND
estrito nunca casava e o fallback OR injetava ruído que o RRF não sabe descontar.

A decisão se mantém, com um refinamento: **a perna lexical entra na fusão apenas com termos
exatos** (tokens com dígito, siglas, frases entre aspas), casados com AND. Sem termo exato, a
híbrida degenera para a semântica — que é o comportamento certo quando a lexical não tem nada
preciso a dizer. RRF continua sendo a fusão; o que mudou é *o que* a perna lexical traz para ela.

O que não mudou: o índice, o schema, a coluna `tsv` e o modo `lexical` puro (útil sem chave do
Gemini e como diagnóstico).
