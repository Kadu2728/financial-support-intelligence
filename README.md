# Financial Support Intelligence

Plataforma interna de inteligência operacional para equipes de suporte de instituições financeiras.
Analistas perguntam em linguagem natural sobre políticas, procedimentos e manuais internos, e
recebem respostas fundamentadas **com as fontes exatas** — documento, seção e trecho utilizado.

> **Status:** em desenvolvimento. Fase 4 de 11 concluída (sistema de documentos).
> O plano de fases está em [`docs/architecture.md`](docs/architecture.md).

---

## O problema

Uma equipe de suporte opera sobre dezenas de manuais e normativos internos. Encontrar a resposta
correta exige saber **em qual documento** e **em qual seção** ela está — conhecimento que vive na
cabeça dos analistas mais experientes. O resultado é tempo de atendimento alto, respostas
inconsistentes entre analistas e onboarding lento.

## A solução

Um sistema de RAG (Retrieval-Augmented Generation) sobre o acervo interno, com três características
que o distinguem de um chatbot:

1. **Toda resposta cita suas fontes**, e o analista consegue abrir o trecho exato que a originou.
2. **O sistema recusa responder** quando não há evidência suficiente no acervo, em vez de inventar.
3. **As lacunas viram métrica** — perguntas que o acervo não responde são medidas e apresentadas
   como indicador acionável.

---

## Stack

| Camada | Tecnologia |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui |
| Backend | Python 3.12+, FastAPI, Pydantic v2 |
| Banco | PostgreSQL 16 (Neon) + pgvector + full-text search |
| IA | Google Gemini (embeddings e geração) |
| Storage | Cloudflare R2 (S3-compatible) |
| Deploy | Vercel (frontend), Railway (backend), Neon (banco) |

---

## Como funciona o RAG

### Ingestão

```
UPLOAD → validação (magic bytes, checksum) → storage → versão PENDING
       → enfileira job → 202 Accepted
                │
   worker: EXTRAÇÃO → NORMALIZAÇÃO → CHUNKING → EMBEDDINGS → INDEXAÇÃO → READY
```

O processamento é assíncrono desde o início: extrair e embeddar um PDF de 200 páginas leva minutos
e não cabe em um request HTTP. A fila é a própria tabela `processing_jobs`, consumida com
`FOR UPDATE SKIP LOCKED` — sem broker externo
([ADR-0004](docs/adr/0004-fila-em-postgres.md)).

### Consulta

```
PERGUNTA → embedding
         → BUSCA HÍBRIDA: [pgvector cosine] + [full-text pt-BR] → fusão RRF → top-8
         → GATE DE EVIDÊNCIA ──sem evidência──▶ recusa (sem chamar o LLM)
         → CONTEXTO → GEMINI (JSON mode) → VALIDAÇÃO DE CITAÇÕES → RESPOSTA + FONTES
```

**Busca híbrida, não apenas vetorial.** O corpus é denso em tokens exatos (`PIX`, `Circular 3.978`,
códigos de produto) — casos em que embeddings falham e full-text acerta. E o inverso vale para
paráfrases. As duas pernas são fundidas por Reciprocal Rank Fusion, tudo dentro do PostgreSQL
([ADR-0002](docs/adr/0002-busca-hibrida-rrf.md)).

### Autenticação

Access token JWT de 15 minutos, refresh **opaco** de 7 dias com rotação e detecção de reuso. O
refresh não é JWT de propósito: validá-lo exige consultar o banco de qualquer forma — é o que
permite revogar — e, sendo a consulta obrigatória, o JWT só adicionaria superfície.

Se um refresh já revogado reaparece, é sinal de roubo e **todas** as sessões do usuário caem. Sem
essa detecção, a rotação seria teatro: o atacante que copiou o token continuaria renovando ao lado
do usuário legítimo.

Os tokens vivem em cookies httpOnly first-party gravados pelo BFF e nunca chegam ao JavaScript do
navegador ([ADR-0003](docs/adr/0003-bff-para-autenticacao.md)).

**Controle de hallucination em cinco camadas**, três delas independentes do comportamento do modelo:
gate de evidência antes da chamada, contrato de prompt, saída estruturada, validação determinística
de citações e confiança calculada
([ADR-0008](docs/adr/0008-controle-de-hallucination.md)).

---

## Estrutura do projeto

```
.
├── backend/
│   ├── app/
│   │   ├── core/          config, logging, errors, middleware
│   │   ├── modules/       auth, users, documents, ingestion, search,
│   │   │                  rag, queries, feedback, intelligence
│   │   └── integrations/  gemini, storage
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/           rotas (App Router) + BFF em app/api
│       ├── components/    ui (shadcn) + componentes de domínio
│       ├── features/      lógica por domínio
│       └── lib/           cliente de API, utilitários
└── docs/
    ├── architecture.md    visão geral
    ├── data-model.md      esquema do banco
    ├── rag-design.md      parâmetros e estratégia de RAG
    └── adr/               decisões de arquitetura
```

Cada módulo do backend segue `router` → `service` → `repository`.
**O router nunca acessa o banco; o repository nunca conhece HTTP.**

---

## Executando localmente

### Pré-requisitos

- Python 3.12+
- Node.js 20+
- Uma conta [Neon](https://neon.tech) (a partir da Fase 2) — o branching do Neon dispensa
  PostgreSQL local e entrega pgvector já habilitado

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate no Linux/macOS
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

API em `http://localhost:8000` · documentação interativa em `/docs`.

#### Migrations

```bash
cd backend
.venv/Scripts/python -m alembic upgrade head      # aplica o schema
.venv/Scripts/python -m alembic downgrade base    # reverte tudo
```

Para revisar o SQL antes de executar — recomendado em produção:

```bash
cd backend && .venv/Scripts/python -m alembic upgrade head --sql
```

A migration inicial cria as extensões `vector`, `pg_trgm` e `citext`, os sete tipos ENUM e as
dez tabelas. É escrita à mão em vez de gerada por `autogenerate` porque a ordem importa: extensões
antes dos tipos de coluna que dependem delas, e tipos ENUM antes das tabelas que os usam — o
`autogenerate` não modela extensões.

#### Primeiro usuário

Não há auto-registro: cadastrar usuários exige um ADMIN autenticado, e o primeiro
administrador precisa ser criado pela linha de comando.

```bash
cd backend && .venv/Scripts/python -m app.cli create-admin --email voce@instituicao.com.br --name "Seu Nome"
```

A senha é lida de forma interativa — nunca por argumento, que ficaria no histórico do shell e
na lista de processos.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Aplicação em `http://localhost:3000`.

### Verificação

```bash
cd backend && .venv/Scripts/python -m pytest && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m mypy app
```

```bash
cd frontend && npm run typecheck && npm run lint
```

Os testes marcados `integration` exigem um PostgreSQL real e são pulados sem ele. Para rodá-los:

```bash
cd backend && DATABASE_URL="postgresql://...-pooler.../db" .venv/Scripts/python -m pytest -m integration
```

Eles cobrem o que um repositório em memória não alcança: que o DDL executa, que os índices existem,
e o comportamento **transacional** — a detecção de reuso de refresh token escreve e depois levanta
exceção, então sem um commit explícito a revogação seria desfeita pelo rollback. Um fake passa nos
dois casos; só um banco de verdade distingue.

---

## Variáveis de ambiente

Cada fase adiciona apenas o que usa. Os arquivos `.env.example` de cada pacote são a referência
completa e versionada; `.env` e `.env.local` nunca vão para o repositório.

**Backend** (`backend/.env`)

| Variável | Fase | Descrição |
|---|---|---|
| `APP_ENV` | 1 | `local` · `staging` · `production` · `test` |
| `LOG_LEVEL` / `LOG_JSON` | 1 | Nível e formato do log (JSON em produção) |
| `CORS_ORIGINS` | 1 | Origens permitidas, separadas por vírgula |
| `DATABASE_URL` | 2 | Connection string do Neon — usar a variante **pooled** |
| `JWT_SECRET_KEY` | 3 | Segredo de assinatura dos tokens |
| `STORAGE_BACKEND` / `S3_*` | 4 | Backend de arquivos (`local` ou `s3`; produção exige `pip install -e '.[s3]'`) |
| `GEMINI_API_KEY` | 5 | Chave da API do Gemini — **somente no backend** |
| `GEMINI_EMBEDDING_MODEL` / `_DIM` | 5 | Modelo e dimensão dos embeddings |
| `GEMINI_GENERATION_MODEL` | 7 | Modelo de geração |
| `RAG_MIN_TOP_SCORE` e afins | 7 | Limiares do gate de evidência (calibrados na Fase 6) |

**Frontend** (`frontend/.env.local`)

| Variável | Fase | Descrição |
|---|---|---|
| `BACKEND_URL` | 1 | URL do FastAPI. **Sem `NEXT_PUBLIC_`**: só o servidor a lê |

> Nenhum segredo usa o prefixo `NEXT_PUBLIC_`. Variáveis com esse prefixo vão para o bundle do
> navegador e são públicas por definição. Como o frontend fala com o backend por meio do BFF
> ([ADR-0003](docs/adr/0003-bff-para-autenticacao.md)), o cliente nunca precisa de credencial.

---

## Deploy

| Serviço | Plataforma | Observação |
|---|---|---|
| Frontend | Vercel | Root directory: `frontend` |
| Backend | Railway | Root directory: `backend`, start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Banco | Neon | Habilitar `vector`, `pg_trgm` e `citext` |
| Arquivos | Cloudflare R2 | Bucket privado, acesso por chave S3 |

Detalhes na Fase 11.

---

## Decisões de arquitetura

As decisões difíceis de reverter estão registradas em [`docs/adr/`](docs/adr), com contexto,
consequências (inclusive as negativas) e alternativas descartadas:

| # | Decisão |
|---|---|
| [0001](docs/adr/0001-monolito-modular.md) | Monolito modular em vez de microsserviços |
| [0002](docs/adr/0002-busca-hibrida-rrf.md) | Busca híbrida (pgvector + full-text) com fusão RRF |
| [0003](docs/adr/0003-bff-para-autenticacao.md) | BFF no Next.js para a sessão autenticada |
| [0004](docs/adr/0004-fila-em-postgres.md) | Fila de processamento em PostgreSQL com SKIP LOCKED |
| [0005](docs/adr/0005-versionamento-de-documentos.md) | Documento e versão como entidades separadas |
| [0006](docs/adr/0006-role-como-enum.md) | Papel como ENUM, não como tabela de domínio |
| [0007](docs/adr/0007-abstracao-de-storage.md) | Abstração de storage com backend S3-compatible |
| [0008](docs/adr/0008-controle-de-hallucination.md) | Controle de hallucination em cinco camadas |

## Roadmap

- [x] **Fase 0** — Arquitetura e planejamento
- [x] **Fase 1** — Setup do monorepo
- [x] **Fase 2** — Banco de dados e migrations
- [x] **Fase 3** — Autenticação e autorização
- [x] **Fase 4** — Sistema de documentos
- [ ] **Fase 5** — Extração, chunking e embeddings
- [ ] **Fase 6** — Busca semântica e híbrida
- [ ] **Fase 7** — RAG e integração com Gemini
- [ ] **Fase 8** — Citações, histórico e feedback
- [ ] **Fase 9** — Dashboard e Support Intelligence
- [ ] **Fase 10** — Testes, segurança e observabilidade
- [ ] **Fase 11** — Polimento e deploy
