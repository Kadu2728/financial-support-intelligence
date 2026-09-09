# ADR-0001 — Monolito modular em vez de microsserviços

- **Status:** Aceito
- **Data:** 2026-09-09
- **Fase:** 0

## Contexto

O sistema tem nove áreas funcionais (auth, documents, ingestion, search, rag, queries, feedback,
intelligence, users). Uma leitura superficial sugeriria separá-las em serviços independentes, e é
comum ver projetos de portfólio fazerem isso para "demonstrar arquitetura distribuída".

As restrições reais são: um único domínio de negócio coeso, um único banco de dados, um time de uma
pessoa e orçamento de infraestrutura próximo de zero.

## Decisão

**Monolito modular**: um único processo FastAPI, com fronteiras internas explícitas entre módulos.

Cada módulo em `app/modules/<nome>/` expõe `router` → `service` → `repository`. A regra estrutural é
que o router nunca acessa o banco e o repository nunca conhece HTTP. Módulos se comunicam pela
camada de serviço, nunca pelo repository um do outro.

## Consequências

### Positivas

- Uma transação de banco cobre operações que cruzam módulos. Em microsserviços, indexar um documento
  e atualizar seu status seriam duas escritas em serviços distintos, exigindo saga ou outbox para
  algo que aqui é um `BEGIN/COMMIT`.
- Deploy único, log único, um `request_id` atravessa a requisição inteira sem tracing distribuído.
- Refactor entre módulos é uma mudança de código, não uma renegociação de contrato de rede.
- Custo de infraestrutura de um serviço.

### Negativas

- Escala como um bloco: se a ingestão consumir CPU, a API de consulta sente. Mitigado porque a
  ingestão já roda fora do ciclo de request (ver [ADR-0004](./0004-fila-em-postgres.md)).
- A disciplina das fronteiras depende de convenção e revisão, não do compilador. Um import
  atravessado entre módulos não quebra o build.

## Alternativas consideradas

**Microsserviços por módulo.** Rejeitado: introduz latência de rede, consistência eventual e
complexidade operacional para resolver problemas de escala e de autonomia de time que este projeto
não tem. Adotar microsserviços sem essas pressões é custo puro.

**Serverless functions por endpoint.** Rejeitado: cold start penaliza justamente o caminho crítico
(RAG já carrega a latência do Gemini), e o worker de ingestão precisa de execução longa, que o
modelo serverless não acomoda bem.

## Caminho de evolução

As fronteiras módulo-a-módulo são exatamente as linhas de corte se a extração vier a ser necessária.
O primeiro candidato natural seria `ingestion`, por ter perfil de recurso diferente do resto.
