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
| Perna lexical (hybrid) | só com **termos exatos** | Tokens com dígito, siglas em caixa alta ou frases entre aspas, casados por `plainto_tsquery` (AND). Sem termo exato, a perna não participa — medido em §10: sobre a pergunta inteira ela só injetava ruído |
| `k` do RRF | 60 | Valor canônico; amortece a influência das primeiras posições |
| Top-K final | 8 | Cabe no orçamento de contexto com folga |
| Dedup | por `section_path` | Evita que 4 chunks da mesma seção ocupem o contexto inteiro |
| Filtro | `is_current = true` | Apenas conteúdo vigente é recuperável |

Ver [ADR-0002](./adr/0002-busca-hibrida-rrf.md) para o porquê da busca híbrida e da escolha de RRF
sobre soma ponderada de scores.

## 5. Gate de evidência

**Calibrado em 2026-09-11** (§10). Os valores de partida (0.55/0.45) eram baixos demais para o
`gemini-embedding-001`, cujo cosine é comprimido:

| Condição | Valor inicial | Calibrado |
|---|---|---|
| Similaridade cosine do melhor chunk | `>= 0.55` | `>= 0.66` |
| Chunks acima do piso | `>= 2` acima de `0.45` | `>= 2` acima de `0.64` |

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
| Modelo | env `GEMINI_GENERATION_MODEL`, padrão `gemini-3.8-flash` — ver latências abaixo |
| Temperatura | 0.2 — resposta factual, não criativa |
| Formato | JSON mode com schema fixo |
| Timeout | 60 s, com erro explícito na UI — sob carga um Flash pode levar 20–50 s |

```json
{ "answer": "string",
  "citations": ["C1", "C4"],
  "confidence": 0.0,
  "insufficient_evidence": false }
```

**Escolha do modelo (medida em 2026-09-11, mesmo prompt de ~470 tokens, JSON mode):**

| Modelo | Latência | Observação |
|---|---|---|
| `gemini-2.5-flash` | — | Aposentado para novos projetos (404 na API) |
| `gemini-3.6-flash` | 54 s | Retornou 503 "high demand" em 3 de 5 chamadas; retry com backoff salvou, mas 30–50 s por resposta é inaceitável na tela |
| **`gemini-3.8-flash`** | **1,9 s** | Mesma qualidade de resposta nas perguntas de avaliação; padrão atual |
| `gemini-3.5-flash-lite` | 1,0 s | Alternativa se custo importar mais que qualidade |

A latência do `3.6` era demanda do serviço, não do prompt: o mesmo payload no `3.8` respondeu em
2 s. O modelo é configuração — trocar não exige deploy.

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

Ferramenta: `scripts/avaliar_busca.py` (exige `GEMINI_API_KEY` e o acervo indexado).

### Resultados

Medidos em 2026-09-11 com `gemini-embedding-001` (768 dims) sobre os 8 documentos do acervo
(60 chunks), K = 8. Recusa = decisão do gate com os limiares calibrados abaixo.

**Antes da correção da perna lexical** (fusão da pergunta inteira, com fallback OR):

| Modo | Literal (5) | Paráfrase (6) | Multi-seção (5) | Fora do acervo (5) |
|---|---|---|---|---|
| semantic | recall 1.00 · MRR 0.90 | 0.83 · 0.75 | 1.00 · 1.00 | recusas 0/5 |
| lexical | 1.00 · 0.60 | 0.17 · 0.06 | 1.00 · 0.53 | 1/5 |
| **hybrid** | 1.00 · **0.77** | **0.33 · 0.17** | 1.00 · 1.00 | 0/5 |

A híbrida era **pior** que a semântica pura. Diagnóstico: `websearch_to_tsquery` (AND de todos os
termos) devolveu zero em 19 das 20 perguntas — linguagem natural nunca casa todos os termos — e a
perna lexical caía no fallback OR, injetando até 30 chunks de palavras comuns que o RRF promovia como
sinal. O gate com os limiares iniciais (0.55/0.45) não recusou nenhuma pergunta fora do acervo:
o cosine deste modelo é comprimido, e "sem resposta" fica em 0.57–0.67.

**Depois** (perna lexical só com termos exatos; gate 0.66/0.64/2):

| Modo | Literal (5) | Paráfrase (6) | Multi-seção (5) | Fora do acervo (5) |
|---|---|---|---|---|
| semantic | 1.00 · 0.90 | 0.83 · 0.75 | 1.00 · 1.00 | recusas 4/5 |
| lexical | 1.00 · 0.60 | 0.17 · 0.06 | 1.00 · 0.53 | 4/5 |
| **hybrid** | 1.00 · **0.90** | **0.83 · 0.75** | 1.00 · 1.00 | **4/5** · 0 indevidas |

Distribuição da similaridade do topo (hybrid): literal 0.687–0.759 · paráfrase 0.664–0.768 ·
multi-seção 0.739–0.773 · **fora do acervo 0.569–0.674**.

Leituras honestas dos números:

- **Neste acervo, a semântica sozinha já resolve as literais.** `gemini-embedding-001` representa
  bem `COD-2041` e `FOR-CAD-017` quando o código aparece literalmente no chunk. A perna lexical
  não melhorou o recall aqui; ela existe pela robustez em acervos maiores, onde o embedding dilui
  o token — e agora só participa quando tem algo preciso a dizer (§4).
- **A única paráfrase perdida (`par-06`) não é falha de retrieval.** O conteúdo da seção 2.2 foi
  recuperado na posição 4, dentro do chunk da seção-mãe "2": as subseções 2.1 e 2.2 eram menores
  que 64 tokens e foram fundidas na mãe pelo chunker, que mantém o rótulo dela. O matcher exige o
  rótulo da subseção. Recall real contando o chunk-mãe: 6/6.
- **Nenhum limiar separa `fora-05` de `par-05`.** "Abertura de conta de pessoa *jurídica*" (fora,
  0.674) e "posso passar meu WhatsApp?" (dentro, 0.664) estão a 0.01 um do outro. Com 0.66 o gate
  deixa `fora-05` passar — e **o modelo recusa** (`insufficient_evidence`), verificado com o RAG
  real. Com 0.68 o gate recusaria os 5/5, mas negaria `par-05`. Ficou 0.66: a camada 1 barra o
  óbvio, a camada 2 barra o sutil. É exatamente para isso que há cinco camadas.

Dois bugs de contrato só apareceram com o modelo real, e viraram testes:

1. O modelo citava `[C1-a8f3e2]` copiando o sufixo aleatório do delimitador; a validação rejeitava
   e produzia uma recusa indevida numa resposta correta. O identificador virou atributo
   (`<trecho-sufixo id="C1">`) e a validação tolera o sufixo quando é o desta requisição.
2. Marcadores compostos `[C1, C2]` não eram reconhecidos nem pela validação nem pelo renderizador.

## 11. Limitações conhecidas

- **`ts_rank_cd` não pondera por raridade do termo (sem IDF).** No fallback OR do modo lexical
  puro, termos frequentes ("conta", "cliente") dominam o ranking — é o que derrubou a híbrida
  antes da correção de §10 e o que mantém o modo `lexical` fraco em paráfrases (recall 0.17).
  BM25 via extensão (`pg_search`) resolveria; adiado até um acervo em que a semântica não baste.
- **Subseções curtas herdam o rótulo da seção-mãe.** Chunks fundidos por tamanho mínimo citam a
  seção maior ("2" em vez de "2.2"). A citação continua correta, só menos precisa.
- **Conjunto de avaliação pequeno (20 perguntas).** Os limiares têm margem de 0.01 no pior caso;
  são configuração, não código, e devem ser recalibrados a cada troca de modelo ou de acervo.
- **Estimativa de tokens é aproximada** (3,9 caracteres/token). Conservadora por desenho; o ponto
  de ajuste é único (`tokens.py`).
- **Rate limiting em memória.** Correto para uma instância; com mais de uma, o teto efetivo se
  multiplica. Trocar por Redis é a única mudança necessária para escalar horizontalmente.
