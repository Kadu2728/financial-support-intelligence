# ADR-0009 — Cliente Gemini por HTTP direto, sem SDK

**Status:** Aceito · **Data:** 2026-09-11 · **Fase:** 5

## Contexto

O sistema usa dois endpoints do Gemini: `batchEmbedContents` (ingestão e consulta) e
`generateContent` em JSON mode (resposta do copilot). A escolha era entre o SDK oficial
(`google-genai`) e chamadas HTTP diretas com `httpx`.

Requisitos que pesaram:

- **Retry seletivo.** 429 e 5xx devem ser retentados com backoff; 400 e 403 não — repetir uma
  chave inválida só atrasa o erro.
- **Timeout explícito** por chamada, com erro próprio que o frontend consegue distinguir
  (`GENERATION_TIMEOUT`).
- **Fake de teste** que implemente o mesmo contrato sem simular um SDK inteiro.
- **Nenhuma tool exposta ao modelo** na chamada de RAG — a mitigação arquitetural contra prompt
  injection ([ADR-0008](./0008-controle-de-hallucination.md)) precisa ser verificável no corpo da
  requisição.

## Decisão

Implementar `GeminiClient` sobre `httpx.AsyncClient`, com dois métodos (`embed`, `generate_json`)
que satisfazem os Protocols `EmbeddingClient` e `GenerationClient`. A chave vai no header
`x-goog-api-key`, nunca na URL. Embeddings são truncados para 768 dimensões
(`outputDimensionality`) e **re-normalizados L2** no cliente.

## Consequências

**Positivas**

- O corpo exato da requisição é código do projeto e é testado (`tests/test_gemini_client.py`):
  task type, dimensão, ausência de `tools`, header da chave.
- Retry, backoff e timeout são visíveis e ajustáveis sem depender do comportamento interno de um
  SDK que muda entre versões.
- Uma dependência (`httpx`, já usada nos testes) em vez de dezenas transitivas.
- O fake de teste tem 40 linhas e implementa o mesmo Protocol.

**Negativas**

- Mudanças na API REST do Gemini exigem alteração aqui; o SDK as absorveria. Mitigação: a
  superfície usada é mínima (dois endpoints, campos estáveis desde a v1beta) e há testes de
  contrato que falham cedo.
- Recursos avançados (streaming, cache de contexto, function calling) não estão disponíveis. Nenhum
  é necessário: streaming atrapalharia a validação de citações, que precisa da resposta completa;
  function calling é explicitamente indesejado.

## Alternativas descartadas

- **`google-genai` SDK.** API pública mudou três vezes em dois anos (`google-generativeai` →
  `google-genai`, com quebra de assinaturas). Traz `google-auth`, `grpc` e afins para expor duas
  funções. O retry embutido não distingue erros retentáveis dos que não são.
- **LangChain / LlamaIndex.** Abstrações sobre abstrações para um pipeline de seis etapas cuja
  lógica de negócio (gate, validação de citações, confiança calculada) é justamente o que não pode
  ficar escondido atrás de um framework. Ver [ADR-0001](./0001-monolito-modular.md) sobre não
  adicionar tecnologia sem problema que a justifique.
