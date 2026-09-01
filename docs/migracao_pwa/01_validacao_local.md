# Migração Telegram → PWA — evidências locais

Data da validação: 2026-09-01
Branch: `codex/pwa-foundation`
Worktree: `D:\Repos\bode-andarilho-pwa`

## Código entregue nesta etapa

- Testes de caracterização e CI para Python 3.12 e Node 22.
- Serviços de comando independentes de canal para eventos e presenças.
- Adapter explícito do payload legado do Telegram, sem associação automática de registros.
- Associação opcional Telegram ↔ perfil por código temporário de uso único, sem expor hash.
- API Starlette `/api/v1` com autenticação Supabase, convites, eventos, rotação segura de link público, cards com legenda reutilizável, presenças, auditoria e endpoint público.
- Auditoria de comandos preserva somente o hash da `Idempotency-Key`; a chave original não é armazenada no metadata.
- Contadores operacionais ficam disponíveis em `GET /api/v1/metrics` somente
  para administrador global; no piloto de uma instância são mantidos em memória.
- PWA React/TypeScript com login OTP, consumo de convite, dashboard, cadastro/edição de loja, edição de evento, operação de evento, revisão de presenças, consulta pública de recibo e compartilhamento assistido.
- Migrations vazias `pwa_v2` com `pwa_private`, grants explícitos, RLS/FORCE RLS, índices de FKs e Storage privado.
- Migration incremental de otimização das políticas RLS (`(select auth.uid())`).
- Dockerfile multiestágio: Node compila a PWA e Python serve API, PWA e webhook na mesma origem.
- Entry point aceita modo somente PWA (`TELEGRAM_ENABLED=false`), no qual webhook,
  scheduler e rotas legadas do Telegram não são registrados.
- O runtime aceita a credencial histórica `SUPABASE_KEY` como fallback de
  servidor, sem promovê-la à configuração pública entregue ao navegador.
- O primeiro bootstrap pode ser concluído pela PWA somente quando o e-mail
  autenticado coincide com `PWA_BOOTSTRAP_EMAIL`; o `PWA_BOOTSTRAP_TOKEN` fica
  restrito ao backend e continua disponível para operação server-to-server.

## Verificações executadas

- `npx supabase migration new create_pwa_v2` — migration gerada pelo CLI.
- `npx supabase db reset` — executado com sucesso; `supabase/seed.sql` mantém o schema vazio.
- `npx supabase db lint --local --schema pwa_v2,pwa_private --level error --fail-on error` — nenhum erro de schema.
- `npx supabase db advisors --local --type all --level warn --fail-on error` — nenhum issue de Security/Performance.
- Catalogo local: dez tabelas com RLS e FORCE RLS ativos; depois do reset, perfis, lojas, eventos e presenças estão vazios.
- Auditoria do catálogo: as dez tabelas retornaram `relrowsecurity=true` e
  `relforcerowsecurity=true`; não há grants de tabela para `anon`, `authenticated`
  recebe somente `SELECT`, `service_role` concentra as mutações e todas as FKs
  possuem índice dedicado.
- RLS com fixtures descartáveis: secretário vê somente a própria loja/evento; outra loja fica invisível; administrador global vê as duas; `anon` não possui grants diretos de leitura/escrita.
- Smoke integrado: configuração pública, `/me`, criação/publicação de evento, link público, presença pendente, recibo, aprovação e geração/upload de card.
- Smoke real local com Auth/REST/Storage/RPC: usuário descartável, bootstrap, loja, associação Telegram, evento público, presença, recibo, aprovação e card — todos os passos retornaram sucesso; o banco foi resetado depois.
- `python -m pytest -q` — 64 testes aprovados nesta revisão, cobrindo também 404/409 de convite, 429 de rate limit, propagação de request ID, métricas restritas, allowlist de lojas-piloto, separação da chave pública do CAPTCHA, arquivamento de loja, visibilidade pública, preparação de card e compatibilidade de credencial.
- Compilação sintática dos 61 arquivos Python — aprovada em cache temporário separado do `__pycache__` do worktree.
- `npm run typecheck`, `npm test` (2 testes de componentes) e `npm run build` — aprovados com Vite 6.4.3; `npm audit` sem vulnerabilidades reportadas.
- Validação de navegador mockada anterior — visitante abriu o evento, enviou presença e consultou o recibo; secretário abriu o dashboard, listou a loja/evento, aprovou a presença, preparou o card e percorreu `prepared → share_initiated → confirmed_by_user`; console da aplicação sem erros.
- `npm run test:e2e` — 3 cenários Playwright aprovados no build de produção: visitante/recibo, secretário/OTP/criação/aprovação e contrato instalável com manifest, ícones, service worker e aviso de atualização; os cenários usam APIs simuladas e não substituem homologação externa.
- A validação de navegador acima é determinística e mockada; não substitui OTP real, dispositivo Android/iPhone, compartilhamento externo ou publicação comprovada.
- Service worker com detecção de atualização e ação explícita de recarga; requisições `/api/` continuam fora do cache.
- Manifest inclui ícones PNG 180/192/512 derivados do ícone institucional e `apple-touch-icon` para instalação em iOS.
- Link público pode ser regenerado após recarregar a agenda; a rotação invalida o link anterior, mantém somente hash no banco e registra auditoria.
- Geração de card retorna legenda independente de Telegram para revisão e cópia assistida no dashboard.
- Visitante pode consultar o status do recibo por token opaco, sem expor e-mail, telefone ou IDs internos.
- Administrador global ou administrador de loja pode emitir convites somente para lojas existentes e não arquivadas; a API rejeita esses casos antes da FK.
- Reset local após fixture do RPC de associação — código consumido uma vez, identidade criada e auditoria registrada; banco retornou vazio.
- Runtime local somente-PWA usando a URL/credencial de backend já existentes e chave pública separada: `/health` e `/` retornaram 200, `/api/v1/config` não incluiu segredo de servidor e `/api/v1/me` sem sessão retornou 401.
- `docker build -t bode-andarilho-pwa:local .` — aprovado.
- Importação de `main` e construção das rotas PWA dentro da imagem Python 3.12 — aprovada com placeholders locais.
- Branch `codex/pwa-foundation` publicada em `origin`; CI `33503102728`, `33503271430` e `33537073491` concluídos com sucesso nos jobs Python 3.12 e Node 22.
- O commit `0698948` foi publicado em `origin/main` por fast-forward e recebeu
  deploy controlado no serviço Render `bode-andarilho`, sem alteração do
  Supabase e mantendo `TELEGRAM_ENABLED=true` e
  `TELEGRAM_MUTATIONS_TO_PWA=false`.
- O build remoto do Render usou Node 22.23.2, passou `typecheck`, gerou o
  frontend Vite e iniciou `python main.py` com status `Deploy succeeded|Live`.
- Smoke público remoto: `/health`, `/`, `/api/v1/config`,
  `/manifest.webmanifest` e `/sw.js` retornaram 200; `/api/v1/me` sem sessão
  retornou 401. A configuração pública informou somente a chave publicável,
  URL do Supabase, URL pública e flags de CAPTCHA; nenhum segredo do backend
  apareceu na resposta.
- O boot remoto confirmou Scheduler iniciado, aplicação Telegram iniciada,
  `setWebhook` e `getWebhookInfo` com HTTP 200, webhook configurado na URL
  pública e zero atualizações pendentes.
- Os loggers de transporte `httpx` e `httpcore` passaram a nível `WARNING` para
  evitar que URLs com credenciais sejam registradas em novos logs operacionais;
  rotação do token do Telegram permanece uma ação separada no BotFather.

## Limites ainda não executados

- A fundação `pwa_v2` foi aplicada ao Supabase remoto autorizado de forma aditiva, sem backfill; os detalhes, a contagem prévia e os gates restantes estão em `docs/migracao_pwa/02_gate_piloto.md`.
- O deploy público controlado foi executado, mas ainda não representa
  homologação autenticada externa: OTP real, Android/iPhone, compartilhamento
  real e publicação comprovada permanecem pendentes.
- OTP real, Android/iPhone, compartilhamento real, 2FA do Instagram, perfil público e publicações permanecem gates do piloto.
- Telegram continua no fluxo legado; somente `/vincular` usa o endpoint opcional e `TELEGRAM_MUTATIONS_TO_PWA` permanece desligada. Quando ativada, a flag redireciona os cadastros centrais de evento e loja para a PWA e falha fechado se a URL pública estiver ausente.
- O corte também aceita `TELEGRAM_MUTATIONS_TO_PWA_STORES` como allowlist de IDs do piloto: a decisão é reavaliada antes da persistência de evento, cancelamento, edição, reabertura, arquivamento e template. Os handlers conversacionais e os Mini Apps legados de loja/sessão falham fechado; lojas não incluídas continuam no legado.
- CAPTCHA público permanece desligado por padrão; quando `PWA_PUBLIC_CAPTCHA_REQUIRED=true`, a PWA carrega o desafio hCaptcha pela chave pública e envia o token, enquanto a chave secreta continua somente no backend.
- As fixtures usadas na validação foram locais e descartáveis; não houve backfill dos registros atuais.
- Nesta retomada, Python 3.12 não estava instalado no host e o Docker local permaneceu indisponível após o reinício; por isso a suíte local Python executou em 3.14 e a reprodução atual de RLS/Storage permanece dependente do CI/Docker. A fundação remota foi apenas aditiva, sem backfill nem alteração das tabelas legadas.
