# Supabase local — PWA v2

A migration foi criada pelo Supabase CLI via `npx` e validada no ambiente local.
A fundação `pwa_v2` já foi aplicada de forma aditiva ao projeto remoto autorizado
por meio do MCP, sem backfill e sem alteração das tabelas legadas. O backup
técnico restaurável, a exposição do schema no PostgREST e a reconciliação do
histórico local/remoto ainda são gates antes do runtime/corte. Antes de usar o
CLI novamente, confirme a versão suportada e leia o `--help`:

```bash
npx supabase --version
npx supabase migration --help
npx supabase start
npx supabase db reset
npx supabase db lint --local --schema pwa_v2,pwa_private --level error --fail-on error
```

O reset local deve ser a primeira validação. Depois dele, testar as políticas
como `anon`, usuário autenticado sem vínculo, secretário de outra loja,
secretário autorizado e administrador global. No projeto remoto, `pwa_v2` foi
confirmado como schema adicional exposto e `pwa_private` permanece fora da
exposição. A tentativa pública de ler uma tabela retorna `42501` por desenho:
as tabelas não concedem grants diretos ao navegador, e as escritas passam pelo
backend autorizado.

No projeto remoto `bode-andarilho` (`dvtbvgmpvfodurcwxnch`), as migrations
registradas são `20260901121956 create_pwa_v2`,
`20260901122542 add_external_identity_association_codes` e
`20260901122613 optimize_pwa_v2_rls_auth_uid`. Como essas versões foram geradas
no momento da aplicação remota pelo MCP e não coincidem com os prefixos dos
arquivos locais, não execute `npx supabase db push` até reconciliar o histórico.

O dump técnico remoto não foi produzido nesta sessão porque não havia token de
acesso do CLI nem URL/senha de banco disponível. A contagem prévia foi somente
leitura e não substitui um backup restaurável.

A associação do Telegram é opcional: a PWA gera um código temporário e o
comando privado `/vincular` o consome uma única vez. Esse fluxo não faz backfill
nem habilita `TELEGRAM_MUTATIONS_TO_PWA`.

O primeiro administrador pode usar o endpoint de bootstrap com o token
temporário em uma operação server-to-server. Para permitir o mesmo passo pela
PWA sem expor o token, configure no provider `PWA_BOOTSTRAP_EMAIL` junto de
`PWA_BOOTSTRAP_TOKEN`; o e-mail autenticado por OTP precisa coincidir exatamente
com essa allowlist.

O deploy/runtime remoto e o corte exigem gates próprios. O procedimento mantém
as tabelas legadas somente leitura durante o piloto e não faz backfill dos dados
de teste.
