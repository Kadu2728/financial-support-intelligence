# Design do RAG

> Parâmetros definidos na Fase 0. Os limiares marcados como **a calibrar** são pontos de partida e
> serão ajustados contra o conjunto de avaliação na Fase 6.
> Decisões estruturais: [ADR-0002](./adr/0002-busca-hibrida-rrf.md) (busca híbrida) e
> [ADR-0008](./adr/0008-controle-de-hallucination.md) (anti-hallucination).

## 1. Embeddings

| Parâmetro | Valor | Justificativa |
|---|---|---|
| Modelo | `gemini-embedding-001` | Configurável por env. Confirmar o nome vigente na documentação do Google no momento do setup — nomes de modelo rotacionam |
| Dimensões | **768** | HNSW no pgvector indexa até 2000 dimensões. 768 custa 4× menos armazenamento que 3072 e é suficiente para um corpus de milhares de chunks |
| Normalização | L2 obrigatória | Truncação Matryoshka **exige** re-normalização. Sem ela, a similaridade cosine degrada de forma silenciosa |
| `task_type` (ingestão) | `RETRIEVAL_DOCUMENT` | |
| `task_type` (consulta) | `RETRIEVAL_QUERY` | Embeddings assimétricos. Usar o mesmo tipo nos dois lados reduz recall de forma mensurável |
| Batch | 64 chunks por chamada | Reduz round-trips; retry com backoff exponencial por lote |

O par `embedding_model` + dimensão é persistido em cada chunk. Sem isso, uma troca de modelo torna
impossível saber o que re-embeddar, e vetores de espaços diferentes convivendo no mesmo índice
produzem ranking sem significado — sem erro visível.

## 2. Chunking

**Estratégia: structure-aware, nunca corte cego por caractere.**

```
documento → detecta hierarquia de seções (1., 1.2, 1.2.3, títulos em caixa alta)
          → um chunk por seção
          → seção maior que o limite: janela deslizante DENTRO da seção
          → nunca atravessa fronteira de seção
```

| Parâmetro | Valor | Justificativa |
|---|---|---|
| Alvo | ~512 tokens | Chunk menor produz citação mais precisa. A rastreabilidade "Seção 3.2" em vez de "Capítulo 3" **depende** disso |
| Máximo | 800 tokens | |
| Mínimo | 64 tokens | Abaixo disso, funde com o vizinho — fragmentos curtos poluem o ranking |
| Overlap | 15% (~80 tokens) | Evita cortar um procedimento ao meio. Acima de 20% infla o índice sem ganho de recall |

**Metadados por chunk:** `section_path`, `section_label`, `page_number`, `char_start`, `char_end`.

Esses campos não são acessórios — são o que transforma "a IA respondeu" em "a IA respondeu **e eu
posso verificar onde**". `char_start`/`char_end` permitem destacar o trecho exato no visualizador.

## 3. Normalização (pré-chunking)

Aplicada ao texto extraído, nesta ordem:

1. Remoção de cabeçalho e rodapé repetidos (detectados por recorrência entre páginas).
2. Rejunção de palavras hifenizadas por quebra de linha.
3. Colapso de espaços em branco redundantes, preservando quebras de parágrafo.
4. Detecção da hierarquia de seções por padrão de numeração e formatação.
5. Descarte de páginas com conteúdo residual (menos de ~40 caracteres úteis).

O texto normalizado é a base dos offsets `char_start`/`char_end` — normalizar depois do chunking
invalidaria as posições.

## 4. Recuperação

```
pergunta
   ├─▶ semântica:  pgvector, cosine, HNSW, top-30
   └─▶ lexical:    tsvector 'portuguese', ts_rank_cd, GIN, top-30
                        │
                   RRF (k = 60):  score(d) = Σ 1 / (60 + rank_i(d))
                        │
                   dedup por section_path  →  top-8
```

| Parâmetro | Valor | Justificativa |
|---|---|---|
| Candidatos por perna | 30 | Recall alto antes da fusão |
| `k` do RRF | 60 | Valor canônico; amortece a influência das primeiras posições |
| Top-K final | 8 | Cabe no orçamento de contexto com folga |
| Dedup | por `section_path` | Evita que 4 chunks da mesma seção ocupem o contexto inteiro |
| Filtro | `is_current = true` | Apenas conteúdo vigente é recuperável |

Ver [ADR-0002](./adr/0002-busca-hibrida-rrf.md) para o porquê da busca híbrida e da escolha de RRF
sobre soma ponderada de scores.

## 5. Gate de evidência

**A calibrar na Fase 6.** Valores de partida:

| Condição | Valor inicial |
|---|---|
| Similaridade cosine do melhor chunk | `>= 0.55` |
| Chunks acima do piso | `>= 2` acima de `0.45` |

Se qualquer condição falhar, o sistema retorna a recusa canônica **sem chamar o Gemini**.

Os limiares vivem em configuração (`RAG_MIN_TOP_SCORE`, `RAG_MIN_SUPPORT_SCORE`,
`RAG_MIN_SUPPORT_COUNT`), nunca no código: recalibrar não pode exigir deploy.

## 6. Construção do contexto

| Parâmetro | Valor |
|---|---|
| Orçamento | ~6.000 tokens |
| Corte | por token acumulado, não por número de chunks |
| Ordenação | por score de fusão, decrescente |

Formato de cada bloco:

```
<C1 documento="Manual de Cadastro" secao="3.2 Atualização Cadastral" pagina="14">
{conteúdo do chunk}
</C1>
```

O identificador `C1` é o que o modelo deve citar, e é o que a validação confere. Os metadados no
atributo permitem que o modelo referencie a seção naturalmente no texto da resposta.

## 7. Geração

| Parâmetro | Valor |
|---|---|
| Modelo | env `GEMINI_GENERATION_MODEL`, classe Flash |
| Temperatura | 0.2 — resposta factual, não criativa |
| Formato | JSON mode com schema fixo |
| Timeout | 30 s, com erro explícito na UI |

```json
{ "answer": "string",
  "citations": ["C1", "C4"],
  "confidence": 0.0,
  "insufficient_evidence": false }
```

## 8. Defesa contra prompt injection

Os documentos são enviados por ADMIN, então o risco é baixo. O princípio se mantém:
**conteúdo recuperado é dado, nunca instrução.**

1. **Nenhuma tool é exposta ao modelo na chamada de RAG.** Sem tools, uma injeção não tem para onde
   escalar. É a mitigação mais forte, e é arquitetural, não textual.
2. Delimitadores de bloco com sufixo aleatório por requisição, impossível de adivinhar pelo conteúdo.
3. Instrução explícita de que nada dentro dos blocos de contexto é comando.
4. Sanitização: remoção de caracteres de controle e de tentativas de fechar delimitador.
5. Pergunta do usuário em bloco separado do contexto, com validação de tamanho.

## 9. Confiança exibida

Calculada, não auto-reportada:

```
confidence = f(top_score, densidade de citações válidas, cobertura do contexto)
```

O valor que o modelo reporta sobre si é armazenado em `answers.raw_response` para análise, mas não é
o número mostrado ao usuário. Modelos são mal calibrados ao avaliar a própria certeza.

## 10. Avaliação (Fase 6)

Conjunto de ~20 perguntas construído a partir do acervo de demonstração, cobrindo quatro classes:

| Classe | O que valida |
|---|---|
| Literal | Consulta por código, sigla ou número de norma — a perna lexical deve dominar |
| Paráfrase | Pergunta sem sobreposição de vocabulário — a perna semântica deve dominar |
| Multi-seção | Resposta exige combinar duas seções — valida top-K e dedup |
| Fora do acervo | Pergunta sem resposta possível — **deve** acionar o gate de recusa |

Métricas: recall@8, MRR, taxa de recusa correta e taxa de recusa indevida (falso negativo do gate).

Os três modos (`semantic`, `lexical`, `hybrid`) são medidos no mesmo conjunto. O resultado é
registrado neste documento — a afirmação "busca híbrida é melhor" precisa de número, não de intuição.
