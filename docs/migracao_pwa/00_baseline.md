# Migração Telegram → PWA — baseline de execução

Data da abertura: 2026-08-31
Branch de trabalho: `codex/pwa-foundation`
Base: `origin/main` em `c7c57bf8561a180272fc3f5c2594370eac860ee8`

## Limites desta etapa

- O worktree original permanece separado e não é alterado por esta branch.
- Nenhuma migration foi aplicada ao projeto Supabase remoto.
- Nenhum registro legado foi migrado, removido ou atualizado.
- Nenhuma publicação ou alteração foi feita no Instagram.
- Telegram continua sendo o canal operacional existente.

## Decisões fixadas

1. A nova base lógica usa o schema `pwa_v2`, evitando colisão com as tabelas legadas em `public`.
2. A PWA e o bot consumirão serviços/repositories do mesmo núcleo; não haverá dual-write.
3. O navegador usará somente a chave publicável do Supabase. A service role ficará no backend.
4. Convites, tokens públicos, recibos e chaves de idempotência serão armazenados como hashes.
5. Autorização será derivada de `auth.uid()` → `pwa_v2.perfis` → `pwa_v2.vinculos_loja`; `user_metadata` não é fonte de permissão.
6. O piloto será de uma loja, com novos convites e sem associação automática aos registros de teste.

## Riscos ainda abertos

- O Supabase CLI foi executado via `npx` e o schema foi validado no ambiente local; ainda não existe autorização para aplicar a migration no projeto remoto.
- Os testes locais de RLS usam fixtures descartáveis e não substituem a validação no projeto remoto isolado antes do corte.
- A proteção 2FA, os códigos de recuperação e a separação do Accounts Center do Instagram exigem execução manual pelo proprietário da conta antes do piloto.
- A publicação do Instagram permanecerá manual no MVP; abrir a folha de compartilhamento não será tratado como publicação comprovada.

## Critério de avanço

Cada lote precisa deixar evidência separada de código, testes, commit, publicação, deploy, runtime e homologação visual. O primeiro commit desta branch cobre a rede de segurança e a fundação do núcleo; não autoriza corte nem deploy.
