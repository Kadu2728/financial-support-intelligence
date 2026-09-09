# Modelo de dados

> Esquema alvo, definido na Fase 0. Implementado via Alembic na Fase 2.
> Decisões com trade-off: [ADR-0005](./adr/0005-versionamento-de-documentos.md) (versionamento) e
> [ADR-0006](./adr/0006-role-como-enum.md) (papéis).

## Extensões

```sql
CREATE EXTENSION IF NOT EXISTS vector;    -- embeddings + busca por similaridade
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- busca por título na listagem de documentos
CREATE EXTENSION IF NOT EXISTS citext;    -- e-mail case-insensitive sem LOWER() em todo lugar
```

## Convenções

- **Chaves primárias:** `UUID` gerado na aplicação. Evita que ids sequenciais revelem volume de
  negócio e permite montar objetos antes do INSERT.
- **Timestamps:** `TIMESTAMPTZ`, sempre UTC. `created_at` em toda tabela; `updated_at` onde há mutação.
- **Exclusão:** soft delete (`deleted_at`) apenas em `documents`, onde o histórico de citações exige
  que o registro sobreviva. Nas demais, exclusão física.
- **Enums:** tipos ENUM do PostgreSQL, espelhados por `StrEnum` em Python.
- **Nomenclatura:** tabelas no plural, colunas em `snake_case`, FKs como `<entidade>_id`.

## Enums

```sql
CREATE TYPE user_role       AS ENUM ('ADMIN', 'ANALYST');
CREATE TYPE doc_status      AS ENUM ('PENDING','PROCESSING','READY','FAILED','SUPERSEDED');
CREATE TYPE job_status      AS ENUM ('PENDING','RUNNING','COMPLETED','FAILED');
CREATE TYPE query_status    AS ENUM ('SUCCESS','INSUFFICIENT_EVIDENCE','FAILED');
CREATE TYPE feedback_rating AS ENUM ('POSITIVE','NEGATIVE');
CREATE TYPE feedback_reason AS ENUM ('INCORRECT','INCOMPLETE','WRONG_SOURCE','OUTDATED','OTHER');
```

## Tabelas

### `users`

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `email` | citext | UNIQUE |
| `password_hash` | text | argon2id |
| `full_name` | text | |
| `role` | user_role | DEFAULT `'ANALYST'` |
| `is_active` | boolean | DEFAULT true — desativar preserva o histórico, deletar não |
| `created_at` / `updated_at` / `last_login_at` | timestamptz | |

### `refresh_tokens`

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users` ON DELETE CASCADE |
| `token_hash` | text | UNIQUE. SHA-256 — o token em claro nunca é persistido |
| `expires_at` / `revoked_at` | timestamptz | |
| `user_agent` / `ip_address` | text / inet | contexto para auditoria de sessão |
| `created_at` | timestamptz | |

```sql
CREATE INDEX ON refresh_tokens (user_id) WHERE revoked_at IS NULL;
```

Guardar o hash permite **revogação real no logout** — algo que JWT stateless não oferece.

### `documents` — identidade lógica

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `title` | text | |
| `description` | text | NULL |
| `category` | text | NULL — taxonomia leve para filtro |
| `uploaded_by` | uuid | FK → `users` ON DELETE RESTRICT |
| `created_at` / `updated_at` / `deleted_at` | timestamptz | |

### `document_versions` — identidade física

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `document_id` | uuid | FK → `documents` ON DELETE CASCADE |
| `version_number` | int | |
| `status` | doc_status | |
| `is_current` | boolean | |
| `original_filename` / `mime_type` | text | |
| `file_size_bytes` | bigint | |
| `checksum_sha256` | char(64) | detecta re-upload idêntico |
| `storage_key` | text | gerado pelo servidor — nunca derivado do input |
| `page_count` / `chunk_count` | int | |
| `error_code` / `error_detail` | text | preenchidos quando `status = 'FAILED'` |
| `processed_at` / `created_at` | timestamptz | |

```sql
CREATE UNIQUE INDEX ON document_versions (document_id, version_number);
CREATE UNIQUE INDEX ON document_versions (document_id) WHERE is_current;  -- 1 corrente
CREATE UNIQUE INDEX ON document_versions (checksum_sha256);               -- anti-duplicata
```

### `document_chunks`

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `document_version_id` | uuid | FK → `document_versions` ON DELETE CASCADE |
| `chunk_index` | int | ordem dentro da versão |
| `content` | text | |
| `content_tokens` | int | orçamento de contexto |
| `section_path` | text | `"3. Cadastro > 3.2 Atualização Cadastral"` — vira a citação exibida |
| `section_label` | text | `"3.2"` |
| `page_number` | int | NULL para formatos sem paginação |
| `char_start` / `char_end` | int | offsets no texto extraído — destacam o trecho exato na UI |
| `embedding` | vector(768) | |
| `embedding_model` | text | qual modelo gerou este vetor |
| `tsv` | tsvector | coluna gerada |
| `created_at` | timestamptz | |

```sql
tsv tsvector GENERATED ALWAYS AS (to_tsvector('portuguese', content)) STORED

CREATE UNIQUE INDEX ON document_chunks (document_version_id, chunk_index);
CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON document_chunks USING gin (tsv);
```

Dois pontos que quebram silenciosamente se ignorados:

- `to_tsvector` de **dois argumentos** é `IMMUTABLE`; a de um argumento é apenas `STABLE` e é
  rejeitada em coluna gerada.
- `embedding_model` por chunk é obrigatório. Ao trocar de modelo de embedding é preciso saber quais
  vetores re-gerar, e misturar espaços vetoriais diferentes na mesma busca produz ranking sem
  significado — sem falhar visivelmente.

### `processing_jobs`

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `document_version_id` | uuid | FK → `document_versions` ON DELETE CASCADE |
| `job_type` | text | `'INGEST'` na v1 |
| `status` | job_status | |
| `attempts` / `max_attempts` | int | |
| `last_error` | text | |
| `started_at` / `finished_at` / `created_at` | timestamptz | |

```sql
CREATE INDEX ON processing_jobs (status, created_at) WHERE status = 'PENDING';
```

Ver [ADR-0004](./adr/0004-fila-em-postgres.md).

### `queries` — tabela quente de analytics

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users` ON DELETE RESTRICT |
| `question` | text | |
| `status` | query_status | |
| `embedding` | vector(768) | reaproveitado pelo Intelligence — custo marginal zero |
| `chunks_retrieved` | int | |
| `top_score` / `confidence` | real | |
| `retrieval_ms` / `generation_ms` / `total_ms` | int | |
| `model` | text | qual modelo gerou — comparabilidade ao longo do tempo |
| `prompt_tokens` / `completion_tokens` | int | custo por consulta |
| `error_code` | text | |
| `created_at` | timestamptz | |

```sql
CREATE INDEX ON queries (user_id, created_at DESC);  -- histórico do usuário
CREATE INDEX ON queries (created_at DESC);           -- séries temporais
CREATE INDEX ON queries (status);                    -- lacunas do acervo
```

### `answers`

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `query_id` | uuid | FK → `queries` ON DELETE CASCADE, UNIQUE |
| `content` | text | |
| `insufficient_evidence` | boolean | |
| `raw_response` | jsonb | resposta bruta do modelo, para depuração |
| `created_at` | timestamptz | |

**Por que tabela separada, sendo 1:1:** o módulo Intelligence varre `queries` continuamente e nunca
precisa do `content`. Separar mantém a tabela quente estreita — mais linhas por página, scans mais
baratos — e deixa espaço para regeneração de resposta sem tocar no registro da consulta. É separação
por padrão de acesso, não por dogma de normalização.

### `citations`

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `answer_id` | uuid | FK → `answers` ON DELETE CASCADE |
| `document_chunk_id` | uuid | FK → `document_chunks` ON DELETE RESTRICT |
| `document_version_id` | uuid | FK — denormalizado, evita 2 joins nas agregações |
| `rank` | int | posição na resposta |
| `score` | real | score de fusão que a trouxe |

```sql
CREATE UNIQUE INDEX ON citations (answer_id, document_chunk_id);
CREATE INDEX ON citations (document_version_id);
```

`ON DELETE RESTRICT` no chunk é deliberado: **uma citação nunca pode ficar órfã**. Excluir um
documento citado exige decisão explícita, não cascata silenciosa.

### `feedback`

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | uuid | PK |
| `query_id` | uuid | FK → `queries` ON DELETE CASCADE |
| `user_id` | uuid | FK → `users` |
| `rating` | feedback_rating | |
| `reason` | feedback_reason | NULL |
| `comment` | text | NULL |
| `created_at` | timestamptz | |

```sql
CREATE UNIQUE INDEX ON feedback (query_id, user_id);  -- um feedback por usuário por consulta
```

## Diagrama de relacionamentos

```
users ──1:N──▶ refresh_tokens
  │
  ├──1:N──▶ documents ──1:N──▶ document_versions ──1:N──▶ document_chunks
  │                                   │                         ▲
  │                                   └──1:N──▶ processing_jobs │
  │                                                             │
  └──1:N──▶ queries ──1:1──▶ answers ──1:N──▶ citations ────────┘
                │
                └──1:N──▶ feedback
```

## Fora do escopo v1

- Particionamento de `queries` — desnecessário no volume previsto.
- Tabela de auditoria genérica — os timestamps e o versionamento já cobrem o necessário.
- `tenant_id` — sistema single-tenant. Adicionar depois é migration aditiva com RLS.
