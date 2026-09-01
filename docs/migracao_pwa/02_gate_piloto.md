# Gate de prontidão do piloto

Atualizado em 2026-09-01, na branch `codex/pwa-foundation`.

## Estado atual

O lote local deixou a PWA operacional para o núcleo de lojas, eventos, cards,
links públicos, solicitações de presença, revisão, convites e associação opcional
do Telegram por código de uso único. O Telegram legado
continua intacto e o schema `pwa_v2` permanece separado e vazio após o reset
local. A fundação do schema também foi aplicada, de forma aditiva, ao projeto
Supabase autorizado; isso não representa corte operacional nem apontamento do
bot ou da PWA para a nova base.

## Evidências concluídas

- worktree original preservado e branch de migração isolada;
- 62 testes Python aprovados nesta revisão, além de compilação sintática em cache
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
- Vitest passou com 2 testes de componentes; Playwright passou com 3 cenários no
  build de produção, incluindo o contrato de instalação/atualização do PWA.
- Manifest agora oferece PNG 180/192/512 e `apple-touch-icon`; `npm audit` não
  reporta vulnerabilidades nas dependências fixadas.
- commits `6eb85f6` e `9046946` publicados em `origin/codex/pwa-foundation`; CI
  `33503102728` e a execução final de documentação `33503271430` concluídos com
  sucesso nos jobs Python 3.12 e Web Node 22, incluindo os E2E.

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
- A configuração de exposição do PostgREST não pôde ser confirmada por
  `current_setting` via SQL. Antes do runtime, o Dashboard/API deve confirmar
  `pwa_v2` como schema exposto e `pwa_private` fora da exposição; a chave secreta
  permanece somente no servidor.

Observação operacional: o MCP registrou as migrations com versões remotas
geradas no momento da aplicação, diferentes dos prefixos de data dos arquivos
locais. Até reconciliar esse histórico com o CLI, não executar `supabase db push`
contra este projeto; novas aplicações devem usar o procedimento documentado e
verificado para evitar reaplicação.

## Gates ainda abertos

1. Gerar ou confirmar backup técnico restaurável antes da janela de corte e
   registrar o artefato fora do chat.
2. Confirmar no Dashboard a exposição do schema `pwa_v2`, mantendo
   `pwa_private` não exposto, e reconciliar o histórico local/remoto de migrations.
3. Revisar e aprovar variáveis do ambiente remoto sem expor service role,
   pepper ou segredo de CAPTCHA no navegador; se o CAPTCHA for ativado,
   configurar também sua chave pública.
4. Publicar o serviço em ambiente isolado e confirmar `/health`, API, Auth,
   Storage e webhook sem habilitar mutações do Telegram.
5. Criar o primeiro administrador e a loja piloto novamente; enviar convites
   novos aos secretários. Nenhum registro legado será associado por nome,
   Telegram ou número de loja.
6. Configurar 2FA do Instagram e do Gmail, códigos de recuperação, foto, bio,
   categoria, conta Business e duas publicações iniciais manualmente.
7. Executar OTP real, teste autenticado em Android e iPhone, compartilhamento
   real e dois ciclos operacionais completos.
8. Ensaiar rollback com Telegram como fallback antes de tornar a PWA oficial.

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
