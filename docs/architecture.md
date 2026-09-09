# Arquitetura — Financial Support Intelligence

> Documento vivo. Decisões pontuais com trade-off relevante ficam em [`adr/`](./adr).
> Última revisão: Fase 1.

## 1. Problema

Equipes de suporte de instituições financeiras operam sobre dezenas de manuais, políticas e
procedimentos internos. Encontrar a resposta correta exige saber **em qual documento** e **em qual
seção** ela está — conhecimento que vive na cabeça dos analistas mais antigos. O custo aparece como
tempo de atendimento alto, respostas inconsistentes entre analistas e onboarding lento.

## 2. Solução

Uma plataforma interna onde o analista pergunta em linguagem natural e recebe uma resposta
fundamentada **com as fontes exatas** — documento, seção e trecho utilizado. A rastreabilidade não é
um extra: em ambiente regulado, uma resposta sem origem verificável não tem valor operacional.

O sistema também mede o que **não** consegue responder, transformando as lacunas do acervo em um
indicador acionável (ver §8).

## 3. Visão geral

```
Vercel (Next.js 16)            Railway (FastAPI)              Neon (PostgreSQL 16)
┌───────────────────┐          ┌────────────────────┐         ┌──────────────────┐
│ RSC + Client Comp.│          │ auth  documents    │         │ pgvector (HNSW)  │
│                   │  Bearer  │ ingestion  search  │ asyncpg │ tsvector (FTS)   │
│ BFF /app/api/*   ─┼─────────▶│ rag  queries       │────────▶│ processing_jobs  │
│ cookie httpOnly   │          │ feedback  intellig.│         └──────────────────┘
└───────────────────┘          │        │           │         ┌──────────────────┐
                               │  worker in-process │────────▶│ Cloudflare R2    │
                               └─────────┬──────────┘         └──────────────────┘
                                         │  HTTPS
                                    Google Gemini
                                  (embeddings + geração)
```

Monolito modular, não microsserviços — ver [ADR-0001](./adr/0001-monolito-modular.md).

## 4. Módulos

| Módulo | Responsabilidade |
|---|---|
| `auth` | Login, refresh com rotação, revogação, hash de senha |
| `users` | Perfil, papéis, ativação |
| `documents` | Ciclo de vida do documento e suas versões |
| `ingestion` | Extração, normalização, chunking, embeddings, indexação |
| `search` | Busca híbrida (vetorial + lexical) com fusão RRF |
| `rag` | Orquestração: retrieval, contexto, geração, validação de citações |
| `queries` | Histórico de consultas e leitura de respostas |
| `feedback` | Avaliação das respostas pelos analistas |
| `intelligence` | Agregações sobre uso, cobertura do acervo e lacunas |

Cada módulo tem a mesma anatomia: `router` (HTTP) → `service` (regra de negócio) → `repository`
(persistência), com `schemas` (Pydantic) e `models` (SQLAlchemy).
**O router nunca acessa o banco; o repository nunca conhece HTTP.**

Integrações externas (`integrations/gemini`, `integrations/storage`) ficam fora de `modules/` — são
detalhes de infraestrutura substituíveis, não domínio.

### Módulos deliberadamente ausentes

- **`ai`** — Gemini é integração, não domínio. Vive em `integrations/gemini`.
- **`citations`** — Citação não tem ciclo de vida próprio: nasce e morre com a `Answer`. É entidade
  de `rag`, não módulo.
- **`admin`** — "Admin" é autorização, não domínio. Implementado como `require_role(ADMIN)` nos
  endpoints existentes. Um módulo `admin` vira lixeira de código órfão.

## 5. Pipeline de ingestão

```
UPLOAD → validação (magic bytes, tamanho, checksum) → storage → document_version(PENDING)
       → enfileira processing_job → 202 Accepted
                                          │
  worker: EXTRAÇÃO → NORMALIZAÇÃO → CHUNKING → EMBEDDINGS → INDEXAÇÃO (1 transação) → READY
```

- **202 imediato.** Extrair e embeddar um PDF de 200 páginas leva minutos; não cabe em request HTTP.
- **Indexação transacional.** Falha no meio não deixa documento parcialmente indexado poluindo a busca.
- **Fila no Postgres** com `FOR UPDATE SKIP LOCKED` — ver [ADR-0004](./adr/0004-fila-em-postgres.md).
- Formatos v1: PDF (com camada de texto), DOCX, Markdown, TXT. PDF escaneado falha com erro
  explícito; OCR é trabalho futuro.

## 6. Pipeline de RAG

```
PERGUNTA → validação → embedding(RETRIEVAL_QUERY)
         → BUSCA HÍBRIDA: [pgvector cosine top-30] + [ts_rank_cd top-30] → RRF → top-8
         → GATE DE EVIDÊNCIA ──falhou──▶ recusa determinística (sem chamar o LLM)
         → CONTEXTO (~6k tokens, blocos <C1..C8>)
         → GEMINI (JSON mode)
         → VALIDAÇÃO DE CITAÇÕES (ids inventados são descartados)
         → PERSISTE query + answer + citations + métricas
```

Parâmetros e justificativas em [`rag-design.md`](./rag-design.md).
Decisões estruturais em [ADR-0002](./adr/0002-busca-hibrida-rrf.md) e
[ADR-0008](./adr/0008-controle-de-hallucination.md).

## 7. Modelo de dados

Entidades: `users`, `refresh_tokens`, `documents`, `document_versions`, `document_chunks`,
`processing_jobs`, `queries`, `answers`, `citations`, `feedback`.

Detalhamento em [`data-model.md`](./data-model.md). Duas decisões com trade-off explícito:
[ADR-0005](./adr/0005-versionamento-de-documentos.md) (versionamento) e
[ADR-0006](./adr/0006-role-como-enum.md) (papéis).

## 8. Support Intelligence

Todo indicador é derivado de dados reais, por consulta SQL rastreável. Nenhum número é estimado,
inferido ou gerado por LLM.

| Indicador | Origem |
|---|---|
| Volume de consultas | `COUNT(queries)` por bucket temporal |
| Documentos mais utilizados | `COUNT(citations)` por `document_version_id` |
| Seções mais consultadas | `COUNT(citations)` por `chunk.section_path` |
| **Perguntas sem resposta** | `status='INSUFFICIENT_EVIDENCE'` ∪ `top_score < limiar` ∪ feedback negativo |
| Cobertura do acervo | Documentos `READY` sem nenhuma citação |
| Saúde operacional | Percentis de `retrieval_ms`, `generation_ms`, `total_ms` |

**Guarda de amostra mínima:** variações percentuais só são exibidas com `n >= 20` na janela base.
Ir de 2 para 3 consultas é "+50%" e é ruído estatístico apresentado como insight. Todo card de KPI
exibe o `n` junto do delta.

## 9. Segurança

| Vetor | Controle |
|---|---|
| Sessão | Cookie httpOnly first-party via BFF — [ADR-0003](./adr/0003-bff-para-autenticacao.md) |
| Senha | `argon2id` (fallback `bcrypt` cost 12) |
| Revogação | `refresh_tokens` com hash SHA-256; logout revoga de fato |
| Autorização | `require_role` no router **e** checagem de ownership no service |
| Enumeração de recursos | Recurso de outro usuário retorna **404**, não 403 |
| Upload malicioso | Magic bytes (não extensão), limite de tamanho, `storage_key` gerado pelo servidor |
| Prompt injection | Conteúdo recuperado é dado, nunca instrução; **nenhuma tool exposta ao modelo** |
| Brute-force / custo | Rate limit em `/auth/login` (por IP) e `/copilot/query` (por usuário) |
| Vazamento em log | Nunca logar senha, token, API key ou conteúdo integral de documento |
| Secrets | `pydantic-settings`; `GEMINI_API_KEY` existe **apenas** no backend |

## 10. Observabilidade

Logs estruturados em JSON com `request_id` (propagado no header `X-Request-ID`) e `user_id`.
Métricas persistidas por consulta: `retrieval_ms`, `generation_ms`, `total_ms`, `chunks_retrieved`,
`top_score`, tokens de prompt e de resposta. Erros carregam `error_code` estável para correlação.

## 11. Riscos conhecidos

| Risco | Mitigação |
|---|---|
| Filesystem efêmero no Railway apaga uploads | `StorageBackend` + R2 — [ADR-0007](./adr/0007-abstracao-de-storage.md) |
| Cold start do Neon (scale-to-zero) | Connection string *pooled*, `pool_pre_ping`, pool pequeno |
| Quota / rate limit do Gemini | Batch de embeddings, retry com backoff, erro explícito na UI |
| Limiares de retrieval mal calibrados | Conjunto de avaliação na Fase 6; limiares em config, não no código |
| PDF sem camada de texto | Falha explícita com `error_code`; OCR documentado como próximo passo |
| Nomes de modelo do Gemini mudam | Sempre via variável de ambiente, nunca hardcoded |

## 12. Próximos passos para escalar

Fora do escopo v1, mas o desenho já acomoda:

1. **Worker separado** — trocar a implementação de `JobQueue`; o pipeline não muda.
2. **Reranking** — cross-encoder entre a fusão RRF e a montagem do contexto.
3. **Cache semântico** — perguntas quase idênticas reaproveitam resposta via similaridade.
4. **OCR** — mais um `TextExtractor`.
5. **Particionamento de `queries`** por mês, quando o volume justificar.
6. **Multi-tenant** — `tenant_id` e RLS no PostgreSQL.
