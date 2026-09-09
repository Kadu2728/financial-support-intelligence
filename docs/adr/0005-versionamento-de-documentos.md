# ADR-0005 — Documento e versão como entidades separadas

- **Status:** Aceito
- **Data:** 2026-09-09
- **Fase:** 0

## Contexto

O modelo mais simples ligaria `document_chunks` diretamente a `documents`. Uma atualização do manual
seria: apagar os chunks antigos, inserir os novos.

Esse modelo tem uma falha que só aparece com o tempo. As citações persistidas em `citations` apontam
para chunks. Se os chunks forem substituídos quando o documento é atualizado, **toda resposta
histórica passa a citar um conteúdo que não é mais o conteúdo que a gerou**.

O analista abre uma consulta de três meses atrás, clica na fonte, e lê um texto diferente daquele em
que a resposta se baseou. A citação vira mentira retroativa — e a rastreabilidade, que é o requisito
central do produto, deixa de existir exatamente onde mais importa: no registro histórico.

Políticas e procedimentos de instituição financeira são, por natureza, versionados. O modelo de dados
deve refletir isso.

## Decisão

Separar a entidade lógica da entidade física:

- **`documents`** — a identidade estável. "Manual de Cadastro" é um `document`, para sempre.
- **`document_versions`** — o arquivo concreto e seus chunks. Cada upload cria uma nova versão.

`document_chunks` referencia `document_version_id`. `citations` referencia o chunk e, de forma
denormalizada, a `document_version_id`.

Um índice parcial garante a invariante de versão corrente:

```sql
CREATE UNIQUE INDEX ON document_versions (document_id) WHERE is_current;
```

A busca filtra por `is_current = true` — apenas o conteúdo vigente é recuperável. Versões anteriores
permanecem legíveis pela via de citação, mas nunca voltam a produzir novas respostas.

## Consequências

### Positivas

- **Citações imutáveis.** Uma resposta de três meses atrás continua apontando para o texto exato que
  a fundamentou. É isso que torna o histórico auditável.
- Trilha de auditoria natural: quando o procedimento mudou, e qual versão vigorava em cada data.
- Reprocessamento seguro: uma falha ao processar a v2 não derruba a v1, que continua servindo a busca.
- `status` de versão (`PENDING`/`PROCESSING`/`READY`/`FAILED`/`SUPERSEDED`) modela o ciclo real. Sem
  versões, esse status ficaria no documento e a transição para "atualizando" tornaria o documento
  inteiro indisponível durante o processamento.

### Negativas

- Uma tabela e um nível de indireção a mais. Toda query de chunk passa por `document_versions`.
- `citations` guarda `document_version_id` denormalizado para evitar dois joins nas agregações do
  Intelligence — denormalização deliberada, com o custo de consistência que isso implica (mitigado
  por a coluna ser imutável após a escrita).
- Chunks de versões antigas ocupam espaço indefinidamente. Uma política de retenção pode ser
  necessária no futuro; fora do escopo v1.

## Alternativas consideradas

**Chunks ligados diretamente a `documents`.** Rejeitado pelo motivo central deste ADR. É a única
entidade da modelagem que mantive mesmo priorizando simplicidade, porque seu custo é uma tabela fina
e seu benefício é a integridade do requisito principal do produto.

**Copiar o texto do chunk para dentro de `citations`.** Preservaria o trecho citado sem versionar
nada. Rejeitado: duplica conteúdo, não preserva o documento ao redor do trecho (o usuário precisa
abrir a fonte no contexto), e não resolve o status de processamento.

**Versionamento apenas do arquivo, com chunks sempre substituídos.** Rejeitado: preserva o PDF, mas
não o recorte que gerou a citação. O `char_start`/`char_end` do chunk antigo apontaria para offsets
de um texto que mudou.
