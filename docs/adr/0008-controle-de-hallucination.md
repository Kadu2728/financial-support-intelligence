# ADR-0008 — Controle de hallucination em cinco camadas

- **Status:** Aceito
- **Data:** 2026-09-09
- **Fase:** 0

## Contexto

Em uma ferramenta de suporte de instituição financeira, uma resposta inventada é pior do que
nenhuma resposta. O analista repassa a informação ao cliente, e o erro se materializa como
atendimento incorreto, retrabalho ou exposição regulatória.

A abordagem usual — pedir ao modelo, no prompt, que "responda apenas com base no contexto" — é
necessária e insuficiente. Instrução em linguagem natural é uma solicitação, não uma garantia.

O requisito é que o sistema declare explicitamente quando não sabe.

## Decisão

Cinco camadas independentes, sendo que **três não dependem do comportamento do modelo**.

### 1. Gate de evidência, antes do LLM

Após o retrieval, se o melhor score fica abaixo do limiar, ou se há menos de dois chunks acima do
piso, o sistema retorna a recusa canônica **sem chamar o Gemini**.

Determinístico, gratuito, e imune a alucinação por construção — não há geração para alucinar.
Também é a defesa mais barata: perguntas fora do acervo não consomem cota de API.

### 2. Contrato de prompt

Blocos de contexto identificados (`<C1>` … `<C8>`), instrução de responder exclusivamente a partir
deles, obrigação de citar o identificador de cada afirmação, e instrução explícita de declarar
insuficiência quando o contexto não cobrir a pergunta.

### 3. Saída estruturada

Gemini em modo JSON com schema fixo:

```json
{ "answer": "...", "citations": ["C1", "C4"],
  "confidence": 0.0, "insufficient_evidence": false }
```

Elimina parsing de texto livre e a classe inteira de bugs associada.

### 4. Validação pós-geração — a camada decisiva

Todo identificador citado é conferido contra o conjunto efetivamente recuperado:

- Identificador inexistente é **descartado** (o modelo não tem autoridade sobre suas próprias fontes).
- Se, após o descarte, restarem zero citações válidas, a resposta é **rebaixada** para
  insuficiência de evidência, independentemente do que o modelo produziu.

Uma resposta sem fonte verificável não é exibida como resposta.

### 5. Confiança calculada, não auto-reportada

O `confidence` mostrado ao usuário é derivado dos scores de retrieval e da cobertura de citações
sobre o texto gerado. O valor que o modelo reporta sobre si mesmo é registrado em `raw_response`
para análise, mas **não é o número exibido**. Modelos são mal calibrados ao avaliar a própria certeza.

## Consequências

### Positivas

- Falha em direção segura: na dúvida, o sistema recusa em vez de inventar.
- As camadas 1, 4 e 5 são código determinístico e testável — não dependem de o modelo obedecer.
- Recusas viram dado de produto: alimentam o indicador de lacunas do acervo
  (`architecture.md` §8), transformando a limitação em informação acionável.
- Economia real de chamadas ao Gemini.

### Negativas

- Limiares mal calibrados geram falsos negativos: o sistema recusa perguntas que teria condições de
  responder. É o erro que preferimos cometer, e é mensurável — o conjunto de avaliação da Fase 6
  mede exatamente essa taxa, e os limiares vivem em configuração, não no código.
- O modo JSON restringe a formatação da resposta.
- Latência adicional da validação, na casa de microssegundos.

## Alternativas consideradas

**Apenas instrução no prompt.** Rejeitado: sem verificação, uma citação inventada chega ao usuário
com a mesma aparência de uma verdadeira. É precisamente o modo de falha mais perigoso, porque a
fonte falsa aumenta a confiança do analista na resposta errada.

**LLM-as-judge para verificar a resposta.** Uma segunda chamada avaliando se a resposta é
sustentada pelo contexto. Rejeitado para a v1: dobra custo e latência, e desloca o problema — o
juiz também pode alucinar. A validação determinística de citações resolve o caso principal a custo
próximo de zero.

**Verificação por entailment (NLI) frase a frase.** Rejeitado: exige outro modelo, aumenta latência
significativamente e é desproporcional ao escopo. Registrado como possível evolução.
