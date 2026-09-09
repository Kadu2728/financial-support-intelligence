# ADR-0006 — Papel como ENUM, não como tabela de domínio

- **Status:** Aceito
- **Data:** 2026-09-09
- **Fase:** 0

## Contexto

O levantamento inicial listava `Role` como entidade, o que sugere o modelo clássico de RBAC:
tabelas `roles`, `permissions`, `role_permissions`, `user_roles`.

O requisito real é: dois papéis, `ADMIN` e `ANALYST`, conhecidos em tempo de escrita do código, com
regras fixas — apenas `ADMIN` administra documentos.

## Decisão

Coluna `role user_role NOT NULL DEFAULT 'ANALYST'`, com `user_role` sendo um ENUM do PostgreSQL
espelhado por um `enum.StrEnum` em Python.

A autorização é uma dependency do FastAPI:

```python
@router.post("/documents", dependencies=[Depends(require_role(Role.ADMIN))])
```

Complementada por checagem de ownership na camada de serviço quando o recurso pertence a um usuário
específico — a dependency responde "pode acessar esta rota?", o serviço responde "pode acessar
**este registro**?". As duas perguntas são distintas e ambas precisam de resposta.

## Consequências

### Positivas

- Zero joins para autorizar. Com tabela de papéis, toda requisição autenticada pagaria um join extra
  (dois, com permissões) para ler um dado que nunca muda em runtime.
- O ENUM é verificado pelo banco: `role = 'ADMIM'` falha na escrita, não em produção.
- O `StrEnum` correspondente dá exaustividade no type checker: um novo papel faz o `mypy` apontar
  todos os pontos que precisam tratá-lo.
- Autorização legível no próprio decorator do endpoint, sem consultar dados para entender a regra.

### Negativas

- Criar um papel novo exige migration e deploy. Correto para este domínio: papel não é dado
  operacional, é regra de negócio, e regra de negócio deve passar por revisão de código.
- Não suporta permissões granulares por usuário. Não é requisito.

## Alternativas consideradas

**Tabelas `roles` + `permissions` + `role_permissions`.** Rejeitado como overengineering. Adiciona
quatro tabelas, joins em todo request autenticado e uma tela de administração de papéis, para
modelar dois valores fixos. Pagar hoje por flexibilidade que talvez nunca seja exercida é exatamente
o custo que o projeto se propõe a evitar.

**Coluna de texto livre.** Rejeitado: sem garantia do banco, erros de digitação viram bugs de
autorização — a pior classe de bug para se descobrir tarde.

**Flags booleanas (`is_admin`).** Rejeitado: não escala além de dois papéis e não expressa exclusão
mútua. Um `is_admin=true, is_analyst=true` seria representável e sem significado.

## Caminho de evolução

Se RBAC dinâmico se tornar requisito, a migração é aditiva: criar `roles`, popular a partir dos
valores do ENUM, adicionar `user_roles`, e trocar a implementação de `require_role`. A superfície de
código afetada é uma única dependency, porque nenhum outro ponto do sistema consulta o papel
diretamente.
