# Gate de prontidão do piloto

Atualizado em 2026-09-01, na branch `codex/pwa-foundation`.

## Estado atual

O lote local deixou a PWA operacional para o núcleo de lojas, eventos, cards,
links públicos, solicitações de presença, revisão, convites e associação opcional
do Telegram por código de uso único. O Telegram legado
continua intacto e o schema `pwa_v2` permanece separado e vazio após o reset
local. A fundação do schema também foi aplicada, de forma aditiva, ao projeto
Supabase autorizado; a PWA agora está publicada em coexistência e usa o núcleo
novo, enquanto o bot Telegram continua apontando para o legado. Isso ainda não
representa corte operacional nem migração de registros.

## Evidências concluídas

- worktree original preservado e branch de migração isolada;
- 67 testes Python aprovados nesta revisão, além de compilação sintática em cache
  temporário;
- typecheck, 2 testes de componentes e build React aprovados;
- schema local com RLS/FORCE RLS, grants e lint sem erro;
- Security/Performance Advisors locais sem issues;
- RPC de associação validado com fixture descartável: consumo único, identidade
  vinculada e auditoria; reset posterior deixou as tabelas vazias;
- smoke integrado real local aprovado com Auth, REST, Storage e RPC, incluindo o
  fluxo completo de evento público, presença, recibo, aprovação e card;
- smoke integrado local de Auth/API/repository/Storage executado antes deste lote;
- painel visual conferido em desktop e mobile com mocks, sem homologação externa;
- Playwright local percorreu os fluxos mockados de visitante e secretário, incluindo
  recibo, aprovação de presença, card e os estados de compartilhamento assistido.
- Vitest passou com 2 testes de componentes; Playwright passou com 4 cenários no
  build de produção, incluindo bootstrap do primeiro administrador sem expor o
  token ao navegador e o contrato de instalação/atualização do PWA.
- Manifest agora oferece PNG 180/192/512 e `apple-touch-icon`; `npm audit` não
  reporta vulnerabilidades nas dependências fixadas.
- commit `81e23b2` publicado em `origin/codex/pwa-foundation`; CI `33543798445`
  concluída com sucesso nos jobs Python 3.12 e Web Node 22, incluindo os E2E do
  bootstrap.
- commit `81e23b2` publicado em `origin/main` por fast-forward; o serviço Render
  `bode-andarilho` recebeu deploy controlado com build remoto Node 22.23.2,
  `typecheck` aprovado e status `Deploy succeeded|Live`.
- Smoke remoto público aprovado: `/health`, `/`, `/api/v1/config`, manifest e
  service worker retornaram 200; `/api/v1/me` sem sessão retornou 401; a
  resposta de configuração não expõe service role, pepper ou token de
  bootstrap.
- Boot remoto confirmou Scheduler e aplicação Telegram iniciados, webhook
  configurado com HTTP 200 e zero atualizações pendentes. As flags de
  coexistência permanecem `TELEGRAM_ENABLED=true` e
  `TELEGRAM_MUTATIONS_TO_PWA=false`.

## Evidências remotas — fundação do schema

Projeto Supabase `bode-andarilho`, ref
`dvtbvgmpvfodurcwxnch`, região `sa-east-1`, estado observado
`ACTIVE_HEALTHY`, PostgreSQL `17.6.1.084`.

- Antes da aplicação foi feita uma leitura de contagem, sem alterar dados:
  `auth.users` e `auth.identities` estavam com 0 registros; as tabelas legadas
  consultadas tinham 1 loja, 2 membros, 4 eventos, 2 convites, 1 log e 4 objetos
  de Storage; o schema `pwa_v2` estava vazio.
- O dump técnico restaurável não foi gerado: a sessão local não tinha token de
  acesso do Supabase nem `DATABASE_URL`/senha para o fluxo de backup do CLI.
  Como os registros foram declarados descartáveis e a operação foi somente
  aditiva, a aplicação prosseguiu sem tocar nas tabelas legadas. Esse fato mantém
  o backup completo como gate aberto para o corte, e não como evidência de backup.
- Migrations remotas registradas pelo MCP:
  - `20260901121956 create_pwa_v2`;
  - `20260901122542 add_external_identity_association_codes`;
  - `20260901122613 optimize_pwa_v2_rls_auth_uid`.
- O catálogo remoto contém 10 tabelas `pwa_v2`, todas com RLS e `FORCE RLS`; as
  tabelas novas permanecem vazias; o bucket `pwa-private` existe e é privado.
- As funções de privilégio elevado ficam em `pwa_private`, com `SECURITY DEFINER`
  e `search_path` fixo; `bootstrap_admin`, `consume_invite` e
  `consume_external_identity` não podem ser executadas por `anon` ou
  `authenticated`. As políticas de negócio usam `auth.uid()` e os grants não
  concedem escrita direta ao navegador.
- O Security Advisor ainda aponta erros nas tabelas legadas públicas
  (`public.confirmacoes`, `public.membros`, `public.eventos` e `public.lojas`)
  por RLS ausente, além de avisos informativos nas tabelas legadas sem políticas.
  Isso foi separado do schema novo e não será corrigido neste lote para não
  interromper nem alterar o bot legado.
- A configuração de exposição não é refletida por `current_setting` via SQL,
  pois é administrada pela configuração do serviço. Em 2026-09-01, o operador
  salvou `pwa_v2` no Dashboard autenticado e a confirmação externa no REST com
  `Accept-Profile: pwa_v2` deixou de retornar `PGRST106`; a consulta chegou à
  tabela e retornou `42501 permission denied for table perfis`, conforme o
  desenho de não conceder grants diretos ao navegador. `pwa_private` continuou
  retornando `PGRST106`, com somente `public`, `graphql_public` e `pwa_v2`
  expostos. A chave secreta permanece somente no servidor.
- Após a configuração, a leitura de controle confirmou `auth.users=0`,
  `auth.identities=0` e zero registros nas tabelas operacionais consultadas de
  `pwa_v2`; as tabelas legadas consultadas permaneceram em 1 loja, 2 membros,
  4 eventos e 0 confirmações. Não houve criação, backfill ou alteração de dados.

Observação operacional: o MCP registrou as migrations com versões remotas
geradas no momento da aplicação, diferentes dos prefixos de data dos arquivos
locais. Até reconciliar esse histórico com o CLI, não executar `supabase db push`
contra este projeto; novas aplicações devem usar o procedimento documentado e
verificado para evitar reaplicação.

## Entradas necessárias para o runtime

O repositório não contém configuração de deploy do provedor nem credenciais
operacionais. Para o primeiro ambiente isolado, o administrador do serviço deve
preencher no gerenciador de segredos:

- `SUPABASE_URL`: URL do projeto remoto;
- `SUPABASE_ANON_KEY` ou `SUPABASE_PUBLISHABLE_KEY`: somente chave publicável;
- `SUPABASE_SERVICE_ROLE_KEY`: somente no backend; se ausente, o código aceita
  `SUPABASE_KEY`, que é o nome histórico da credencial já usada pelo bot;
- `PWA_TOKEN_PEPPER`: segredo longo e aleatório;
- `PWA_BOOTSTRAP_TOKEN`: token temporário para o primeiro administrador;
- `PWA_BOOTSTRAP_EMAIL`: e-mail exato autorizado a concluir o primeiro
  bootstrap pela PWA; manter vazio até o operador escolher a conta inicial;
- `PWA_PUBLIC_BASE_URL`: URL HTTPS real do serviço;
- `PWA_FRONTEND_DIST=web/dist` no container, se o provider não usar o default;
- `PWA_PUBLIC_CAPTCHA_REQUIRED=false` no ambiente inicial, ou as chaves pública
  e secreta de hCaptcha antes de ligar a proteção;
- `PWA_ENABLED=true`, `TELEGRAM_ENABLED=true`,
  `TELEGRAM_MUTATIONS_TO_PWA=false` e
  `TELEGRAM_MUTATIONS_TO_PWA_STORES=` durante a coexistência;
- `TELEGRAM_TOKEN`, `GRUPO_PRINCIPAL_ID`, `ADMIN_TELEGRAM_ID` e
  `TELEGRAM_WEBHOOK_SECRET` conforme a instalação legada, sem copiá-los para o
  navegador.

O build Node não precisa receber chave do Supabase: a PWA obtém a configuração
publicável por `GET /api/v1/config` na mesma origem. A credencial histórica
`SUPABASE_KEY` nunca é usada como chave pública; é consumida somente pelo
backend. O primeiro bootstrap ainda exige um e-mail real escolhido pelo
operador; nenhum usuário Auth foi criado remotamente nesta etapa.

O endpoint de bootstrap continua aceitando o `X-Bootstrap-Token` para uma
execução server-to-server. Quando `PWA_BOOTSTRAP_EMAIL` também está configurado,
o primeiro usuário autenticado com esse e-mail pode concluir o passo na própria
PWA, sem que o token secreto seja enviado ao navegador. A função transacional
impede uma segunda configuração depois que o administrador global existir.

No serviço Render autorizado, as variáveis do runtime foram configuradas sem
substituir `SUPABASE_KEY`: a chave publicável foi adicionada separadamente,
`PWA_TOKEN_PEPPER` e `PWA_BOOTSTRAP_TOKEN` foram gerados aleatoriamente e
permanecem somente no provider, a URL pública aponta para
`https://bode-andarilho-fv3m.onrender.com`, e o build compila `web` antes de
iniciar `python main.py`.

## Gates ainda abertos

1. Gerar ou confirmar backup técnico restaurável antes da janela de corte e
   registrar o artefato fora do chat.
2. Reconciliar o histórico local/remoto de migrations antes de usar o CLI contra
   o projeto remoto; a exposição de `pwa_v2` já foi confirmada e
   `pwa_private` permanece não exposto.
3. Criar o primeiro administrador e a loja piloto novamente; enviar convites
   novos aos secretários. Nenhum registro legado será associado por nome,
   Telegram ou número de loja.
4. Configurar 2FA do Instagram e do Gmail, códigos de recuperação, foto, bio,
   categoria, conta Business e duas publicações iniciais manualmente.
5. Executar OTP real, teste autenticado em Android e iPhone, compartilhamento
   real e dois ciclos operacionais completos.
6. Ensaiar rollback com Telegram como fallback antes de tornar a PWA oficial.

Os gates de configuração do provider, build, publicação inicial, API pública,
Auth sem sessão, Storage estático e webhook foram fechados nesta retomada. Eles
não equivalem à homologação autenticada do piloto.

O Docker local estava parado após o reinício e não pôde ser aberto nesta sessão;
essa indisponibilidade não alterou o Supabase remoto. O gate de reset, RLS,
Storage e Advisors permanece sustentado pela validação local anterior e pelo CI,
mas deve ser reexecutado quando o daemon estiver disponível antes do corte.

O endpoint `GET /api/v1/metrics` deve ser consultado pelo administrador global
durante cada ciclo para conferir requisições, autenticação, cards, presenças e
falhas. Os contadores são locais ao processo; antes de escalar horizontalmente,
devem ser encaminhados a um coletor externo.

## Critério de corte

Até todos os gates acima estarem registrados, `TELEGRAM_MUTATIONS_TO_PWA` deve
permanecer desligada. `PWA_ENABLED` pode ser ativada em ambiente isolado para
testes, mas não implica corte operacional. Push, workflow, deploy, migration
remota e publicação no Instagram são marcos independentes.

Quando necessário, `TELEGRAM_ENABLED=false` inicia o mesmo serviço em modo
somente PWA: o webhook, scheduler e rotas legadas do Telegram deixam de ser
registrados, sem alterar dados. Esse modo só deve ser usado depois do piloto e
do ensaio de rollback.

Com a flag de corte ligada, os pontos de entrada de cadastro de sessão e loja
não escrevem no legado: orientam o operador para a PWA e falham fechado quando
`PWA_PUBLIC_BASE_URL` não está configurada.

Para um piloto gradual, `TELEGRAM_MUTATIONS_TO_PWA_STORES` pode listar IDs de
lojas separados por vírgula. A allowlist é avaliada no ponto de persistência;
uma loja fora dela permanece no Telegram até novo gate.
