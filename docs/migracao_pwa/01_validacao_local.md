# Migração Telegram → PWA — evidências locais

Data da validação: 2026-08-31
Branch: `codex/pwa-foundation`
Worktree: `D:\Repos\bode-andarilho-pwa`

## Código entregue nesta etapa

- Testes de caracterização e CI para Python 3.12 e Node 22.
- Serviços de comando independentes de canal para eventos e presenças.
- Adapter explícito do payload legado do Telegram, sem associação automática de registros.
- Associação opcional Telegram ↔ perfil por código temporário de uso único, sem expor hash.
- API Starlette `/api/v1` com autenticação Supabase, convites, eventos, rotação segura de link público, cards com legenda reutilizável, presenças, auditoria e endpoint público.
- PWA React/TypeScript com login OTP, consumo de convite, dashboard, cadastro/edição de loja, edição de evento, operação de evento, revisão de presenças e compartilhamento assistido.
- Migrations vazias `pwa_v2` com `pwa_private`, grants explícitos, RLS/FORCE RLS, índices de FKs e Storage privado.
- Dockerfile multiestágio: Node compila a PWA e Python serve API, PWA e webhook na mesma origem.

## Verificações executadas

- `npx supabase migration new create_pwa_v2` — migration gerada pelo CLI.
- `npx supabase db reset` — executado com sucesso; `supabase/seed.sql` mantém o schema vazio.
- `npx supabase db lint --local --schema pwa_v2,pwa_private --level error --fail-on error` — nenhum erro de schema.
- Catalogo local: dez tabelas com RLS e FORCE RLS ativos; depois do reset, perfis, lojas, eventos e presenças estão vazios.
- RLS com fixtures descartáveis: secretário vê somente a própria loja/evento; outra loja fica invisível; administrador global vê as duas; `anon` não possui grants diretos de leitura/escrita.
- Smoke integrado: configuração pública, `/me`, criação/publicação de evento, link público, presença pendente, recibo, aprovação e geração/upload de card.
- Smoke real local com Auth/REST/Storage/RPC: usuário descartável, bootstrap, loja, associação Telegram, evento público, presença, recibo, aprovação e card — todos os passos retornaram sucesso; o banco foi resetado depois.
- `python -m pytest -q` — 41 testes aprovados nesta revisão.
- Compilação sintática dos 61 arquivos Python — aprovada.
- `npm run typecheck` e `npm run build` — aprovados.
- Playwright local com mocks — dashboard autenticado conferido em desktop e viewport móvel; editor e controles de compartilhamento sem erro de console da aplicação.
- Service worker com detecção de atualização e ação explícita de recarga; requisições `/api/` continuam fora do cache.
- Link público pode ser regenerado após recarregar a agenda; a rotação invalida o link anterior, mantém somente hash no banco e registra auditoria.
- Geração de card retorna legenda independente de Telegram para revisão e cópia assistida no dashboard.
- Reset local após fixture do RPC de associação — código consumido uma vez, identidade criada e auditoria registrada; banco retornou vazio.
- `docker build -t bode-andarilho-pwa:local .` — aprovado.
- Importação de `main` e construção das rotas PWA dentro da imagem Python 3.12 — aprovada com placeholders locais.

## Limites ainda não executados

- Nenhuma migration, configuração ou leitura foi feita no Supabase remoto.
- Nenhum push, workflow, deploy ou teste de runtime público foi executado.
- OTP real, Android/iPhone, compartilhamento real, 2FA do Instagram, perfil público e publicações permanecem gates do piloto.
- Telegram continua no fluxo legado; somente `/vincular` usa o endpoint opcional e `TELEGRAM_MUTATIONS_TO_PWA` permanece desligada.
- As fixtures usadas na validação foram locais e descartáveis; não houve backfill dos registros atuais.
