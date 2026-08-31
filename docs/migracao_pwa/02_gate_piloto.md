# Gate de prontidão do piloto

Atualizado em 2026-08-31, na branch `codex/pwa-foundation`.

## Estado atual

O lote local deixou a PWA operacional para o núcleo de lojas, eventos, cards,
links públicos, solicitações de presença, revisão, convites e associação opcional
do Telegram por código de uso único. O Telegram legado
continua intacto e o schema `pwa_v2` permanece separado e vazio após o reset
local. Não existe autorização para apontar produção para este código.

## Evidências concluídas

- worktree original preservado e branch de migração isolada;
- 51 testes Python aprovados nesta revisão, além de compilação sintática em cache
  temporário;
- typecheck e build React aprovados;
- schema local com RLS/FORCE RLS, grants e lint sem erro;
- RPC de associação validado com fixture descartável: consumo único, identidade
  vinculada e auditoria; reset posterior deixou as tabelas vazias;
- smoke integrado real local aprovado com Auth, REST, Storage e RPC, incluindo o
  fluxo completo de evento público, presença, recibo, aprovação e card;
- smoke integrado local de Auth/API/repository/Storage executado antes deste lote;
- painel visual conferido em desktop e mobile com mocks, sem homologação externa.

## Gates ainda abertos

1. Revisar e aprovar variáveis do ambiente remoto sem expor service role,
   pepper ou segredo de CAPTCHA no navegador; se o CAPTCHA for ativado,
   configurar também sua chave pública.
2. Aplicar a migration somente no projeto Supabase autorizado, depois de
   backup técnico e janela de corte.
3. Criar o primeiro administrador e a loja piloto novamente; enviar convites
   novos aos secretários. Nenhum registro legado será associado por nome,
   Telegram ou número de loja.
4. Configurar 2FA do Instagram e do Gmail, códigos de recuperação, foto, bio,
   categoria, conta Business e duas publicações iniciais manualmente.
5. Executar OTP real, teste autenticado em Android e iPhone, compartilhamento
   real e dois ciclos operacionais completos.
6. Ensaiar rollback com Telegram como fallback antes de tornar a PWA oficial.

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
