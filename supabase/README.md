# Supabase local — PWA v2

A migration foi criada pelo Supabase CLI via `npx` e validada no ambiente local.
Ela não foi aplicada ao projeto remoto. Antes de qualquer aplicação remota,
confirme a versão suportada do CLI e execute no repositório:

```bash
npx supabase --version
npx supabase migration --help
npx supabase start
npx supabase db reset
npx supabase db lint --local --schema pwa_v2,pwa_private --level error --fail-on error
```

O reset local deve ser a primeira validação. Depois dele, testar as políticas
como `anon`, usuário autenticado sem vínculo, secretário de outra loja,
secretário autorizado e administrador global. A API REST precisa ter `pwa_v2`
exposto como schema adicional; `pwa_private` não deve ser exposto.

O deploy remoto exige aprovação específica. O corte previsto mantém as tabelas
legadas somente leitura durante o piloto e não faz backfill dos dados de teste.
