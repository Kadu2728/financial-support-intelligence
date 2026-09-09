# ADR-0007 — Abstração de storage de arquivos com backend S3-compatible

- **Status:** Aceito
- **Data:** 2026-09-09
- **Fase:** 0

## Contexto

**O filesystem do Railway é efêmero.** Todo redeploy recria o container e descarta o disco. Salvar
os arquivos enviados em `./uploads` significa que, no próximo deploy, todos os PDFs do acervo somem —
enquanto os registros em `documents` continuam existindo, apontando para arquivos inexistentes.

O sintoma é particularmente ruim: a busca continua funcionando (os chunks estão no banco), as
respostas continuam sendo geradas, mas clicar em "abrir documento" retorna erro. O sistema parece
saudável e está quebrado no requisito de rastreabilidade.

Este é um dos erros mais comuns em projetos implantados nessa classe de plataforma, justamente
porque não aparece em desenvolvimento local.

## Decisão

Uma interface `StorageBackend` com duas implementações selecionadas por variável de ambiente:

```python
class StorageBackend(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
```

- **`LocalStorage`** — desenvolvimento. Grava em `./storage/`, ignorado pelo git.
- **`S3Storage`** — produção. `boto3` apontado para **Cloudflare R2** (API compatível com S3, tier
  gratuito generoso e, decisivamente, **sem cobrança de egress** — relevante porque cada visualização
  de documento é uma leitura).

A `storage_key` é **sempre gerada pelo servidor** a partir de UUIDs
(`documents/{document_id}/{version_id}{ext}`), nunca derivada do nome de arquivo enviado. O nome
original é preservado em `original_filename` apenas para exibição. Isso elimina path traversal por
construção.

## Consequências

### Positivas

- Arquivos sobrevivem a redeploy. O risco mais alto do projeto deixa de existir.
- Interface pequena (quatro métodos) que resolve um problema concreto — não é abstração especulativa.
- Trocar R2 por S3, Backblaze B2 ou MinIO é mudança de configuração, não de código.
- Desenvolvimento local não exige credencial de nuvem nem conexão de rede.
- Backup do banco fica leve: o Postgres guarda metadados e chunks, não binários.

### Negativas

- Mais um serviço externo e mais três variáveis de ambiente em produção.
- Duas implementações a manter e a testar. Mitigado por um conjunto de testes de contrato executado
  contra ambas.
- Dois lugares para apagar em uma exclusão de documento. Ordem definida: apagar o registro primeiro
  (a transação é a fonte da verdade), depois o objeto; um objeto órfão é inofensivo, um registro
  apontando para nada não é.

## Alternativas consideradas

**`BYTEA` no PostgreSQL.** Guardar os bytes no próprio banco. Zero serviços extras e transacionalmente
perfeito. Rejeitado: infla o banco e, com ele, o custo e o tempo de backup e restore; o Neon cobra por
armazenamento; e cada leitura de documento passa a trafegar o binário pela conexão de banco, que é o
recurso mais escasso. Aceitável apenas para acervos de poucos megabytes.

**Não guardar o arquivo original.** Persistir só o texto extraído e os chunks. Elimina o problema por
inteiro, mas remove a capacidade de abrir o documento-fonte — requisito explícito da tela de Copilot.
Rejeitado.

**Volume persistente do Railway.** Resolveria a efemeridade sem serviço externo. Rejeitado: prende o
projeto a uma plataforma específica, complica a execução local e não oferece o modelo de acesso que
uma futura URL assinada exigiria.
