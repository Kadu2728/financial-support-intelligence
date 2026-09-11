# Architecture Decision Records

Registro das decisões de arquitetura com trade-off relevante. Cada ADR documenta o contexto que
forçou a decisão, a decisão em si, suas consequências (incluindo as negativas) e as alternativas
descartadas com o motivo.

Um ADR não é revisado quando a opinião muda — é **substituído** por outro que o supersede. O
histórico permanece.

| # | Decisão | Status |
|---|---|---|
| [0001](./0001-monolito-modular.md) | Monolito modular em vez de microsserviços | Aceito |
| [0002](./0002-busca-hibrida-rrf.md) | Busca híbrida (pgvector + full-text) com fusão RRF | Aceito |
| [0003](./0003-bff-para-autenticacao.md) | BFF no Next.js para a sessão autenticada | Aceito |
| [0004](./0004-fila-em-postgres.md) | Fila de processamento em PostgreSQL com SKIP LOCKED | Aceito |
| [0005](./0005-versionamento-de-documentos.md) | Documento e versão como entidades separadas | Aceito |
| [0006](./0006-role-como-enum.md) | Papel como ENUM, não como tabela de domínio | Aceito |
| [0007](./0007-abstracao-de-storage.md) | Abstração de storage com backend S3-compatible | Aceito |
| [0008](./0008-controle-de-hallucination.md) | Controle de hallucination em cinco camadas | Aceito |
| [0009](./0009-cliente-gemini-http-direto.md) | Cliente Gemini por HTTP direto, sem SDK | Aceito |

## Quando escrever um ADR

Quando a decisão é **difícil de reverter** e alguém razoável poderia ter escolhido diferente.

Escolher `ruff` em vez de `flake8` não é ADR — é preferência trivialmente reversível. Escolher
busca híbrida em vez de puramente vetorial é ADR: molda o esquema, os índices e o pipeline inteiro
de recuperação.
