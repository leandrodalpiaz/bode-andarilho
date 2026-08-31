# Supabase local — PWA v2

O ambiente de execução desta primeira etapa não possui o binário `supabase`.
Por isso a migration foi revisada e versionada manualmente, mas não foi aplicada
ao projeto remoto.

Antes de qualquer aplicação, instalar uma versão suportada do Supabase CLI e
executar no repositório:

```bash
supabase --version
supabase migration --help
supabase start
supabase db reset
supabase db lint
```

O reset local deve ser a primeira validação. Depois dele, testar as políticas
como `anon`, usuário autenticado sem vínculo, secretário de outra loja,
secretário autorizado e administrador global. A API REST precisa ter `pwa_v2`
exposto como schema adicional; `pwa_private` não deve ser exposto.

O deploy remoto exige aprovação específica. O corte previsto mantém as tabelas
legadas somente leitura durante o piloto e não faz backfill dos dados de teste.
