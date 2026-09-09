# ADR-0003 — BFF no Next.js para a sessão autenticada

- **Status:** Aceito
- **Data:** 2026-09-09
- **Fase:** 0

## Contexto

O deploy alvo coloca o frontend na Vercel (`*.vercel.app`) e o backend no Railway
(`*.railway.app`) — **domínios registráveis diferentes**.

Isso significa que um cookie emitido pelo backend é, do ponto de vista do navegador, um **cookie
third-party**. Safari (ITP) descarta esses cookies por padrão, e Chrome e Firefox os bloqueiam
conforme a configuração do usuário. O sintoma é cruel: o login funciona na máquina do desenvolvedor
e falha silenciosamente para uma parcela dos usuários, tipicamente descoberto durante uma demo.

A alternativa comum — guardar o JWT em `localStorage` — elimina o problema de cookie, mas torna a
sessão legível por qualquer JavaScript da página. Um único XSS exfiltra a credencial.

## Decisão

**Backend for Frontend no Next.js.** Route handlers em `src/app/api/*` fazem proxy para o FastAPI e
guardam os tokens em cookies `httpOnly`, `Secure`, `SameSite=Lax` — emitidos pelo **próprio domínio
do frontend**, portanto first-party.

```
browser ──credenciais──▶ /api/auth/login  (Next, mesma origem)
                              │  set-cookie httpOnly (first-party)
                              ▼
                         POST /api/v1/auth/login  (FastAPI)
                              │  { access_token, refresh_token }
browser ──/api/copilot/query──▶ Next lê o cookie, injeta Authorization: Bearer ──▶ FastAPI
```

O FastAPI permanece **stateless e agnóstico de cookie**: ele apenas emite e valida Bearer tokens.
Toda a mecânica de cookie vive na camada Next.

## Consequências

### Positivas

- Cookie first-party: imune ao bloqueio de terceiros, hoje e conforme os navegadores endurecem.
- Token inacessível a JavaScript: XSS não rouba a sessão.
- Sem CORS com `credentials` — a origem do browser é sempre a própria aplicação. A superfície de
  CORS do backend fica restrita a chamadas servidor-a-servidor.
- A `GEMINI_API_KEY` e a URL interna do backend nunca chegam ao bundle do cliente.
- Habilita renderização em Server Components com sessão, sem expor o token ao cliente.

### Negativas

- Um hop de rede adicional (Vercel → Railway), estimado em 30–60 ms. Aceitável: a chamada de RAG já
  é dominada pela latência do Gemini, na casa de segundos.
- Uma camada fina de proxy para manter. Mitigado por um helper único de encaminhamento em
  `lib/bff.ts`, não um handler escrito à mão por rota.
- O runtime do Next passa a ser parte do caminho de autenticação. Se a Vercel cai, o app cai — mas
  isso já era verdade para o frontend.

## Alternativas consideradas

**Cookie cross-site `SameSite=None; Secure` com CORS `allow_credentials`.** Rejeitado: funciona
hoje em Chrome, quebra em Safari, e a tendência dos navegadores é restringir ainda mais. Escolher
uma solução com data de validade conhecida é dívida deliberada sem contrapartida.

**Bearer token em `localStorage`.** Rejeitado: qualquer XSS resulta em comprometimento total da
sessão. É a opção mais simples de implementar e a mais difícil de defender.

**Domínio customizado com subdomínios** (`app.exemplo.com` / `api.exemplo.com`, cookie em
`.exemplo.com`). Tecnicamente correto e resolveria o problema — cookie passa a ser first-party.
Rejeitado por depender de aquisição e configuração de domínio, o que o projeto não pressupõe. Se um
domínio próprio for adotado, esta decisão deve ser revisitada: ela deixaria de ser necessária.
