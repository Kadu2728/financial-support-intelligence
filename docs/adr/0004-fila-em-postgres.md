# ADR-0004 — Fila de processamento em PostgreSQL com SKIP LOCKED

- **Status:** Aceito
- **Data:** 2026-09-09
- **Fase:** 0

## Contexto

Processar um documento (extrair texto, normalizar, chunkar, gerar embeddings, indexar) leva de
dezenas de segundos a vários minutos em um PDF grande. Isso **não cabe em um request HTTP**: o
Railway encerra a conexão, o navegador desiste e o usuário fica sem saber o que aconteceu.

Fazer o processamento síncrono "por enquanto, migrando depois" é a dívida que nunca se paga, porque
o refactor posterior atravessa toda a camada de documentos.

O extremo oposto — Celery com Redis — significa mais um serviço no Railway, mais uma variável de
ambiente, mais um ponto de falha e mais um componente para explicar, tudo para um volume de
processamento que é baixo e em rajadas.

## Decisão

**A tabela `processing_jobs` é a fila.** Um worker in-process, iniciado junto do FastAPI, consome
jobs em laço.

O claim de job usa a primitiva que torna uma fila em Postgres correta sob concorrência:

```sql
SELECT * FROM processing_jobs
WHERE status = 'PENDING' AND attempts < max_attempts
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

`FOR UPDATE SKIP LOCKED` garante que dois workers jamais reivindiquem o mesmo job: linhas já
travadas são ignoradas em vez de bloquear o consumidor.

O restante do sistema conhece apenas a interface:

```python
class JobQueue(Protocol):
    async def enqueue(self, job: JobRequest) -> JobId: ...
    async def claim(self) -> Job | None: ...
    async def complete(self, job_id: JobId) -> None: ...
    async def fail(self, job_id: JobId, error: JobError) -> None: ...
```

## Consequências

### Positivas

- Zero infraestrutura adicional. O banco que já existe passa a ser o broker.
- **Durabilidade e atomicidade de graça:** enfileirar o job e criar a `document_version` acontecem na
  mesma transação. Não existe estado em que a versão exista sem job, ou vice-versa. Com um broker
  externo, isso exigiria o padrão outbox.
- Retry nativo via `attempts` / `max_attempts` com `last_error` persistido.
- Jobs travados são detectáveis por `started_at` antigo com status `RUNNING` — nenhum documento fica
  preso em `PROCESSING` para sempre após um crash.
- Reprocessamento sob demanda é um `UPDATE` de status.
- A fila é inspecionável com SQL comum, o que torna a depuração trivial.

### Negativas

- Polling em vez de push. Com intervalo de poucos segundos, a latência percebida é irrelevante para
  processamento que dura minutos. `LISTEN/NOTIFY` pode reduzir isso depois, se necessário.
- Worker no mesmo processo da API: um pico de ingestão compete por CPU com as requisições. Aceitável
  no volume previsto, e é exatamente o que a interface `JobQueue` permite corrigir sem refactor.
- Não escala para milhares de jobs por segundo. Está a ordens de magnitude do necessário.

## Alternativas consideradas

**Celery + Redis / RQ / ARQ.** Rejeitado agora, viabilizado depois. Resolve um problema de escala que
não existe, ao custo de um serviço a mais e da perda da atomicidade transacional descrita acima.

**`BackgroundTasks` do FastAPI.** Rejeitado: as tarefas vivem apenas em memória. Um restart durante o
processamento perde o trabalho silenciosamente, sem registro e sem possibilidade de retry — o
documento fica em `PROCESSING` indefinidamente.

## Caminho de evolução

Mover o worker para um processo separado é iniciar o mesmo laço em outro entrypoint, apontando para
o mesmo banco. `SKIP LOCKED` já garante a corretude com múltiplos consumidores. Trocar para um broker
dedicado é escrever outra implementação de `JobQueue`; o pipeline de ingestão não é tocado.
