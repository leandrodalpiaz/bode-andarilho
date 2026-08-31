# Gate de prontidão do piloto

Atualizado em 2026-08-31, na branch `codex/pwa-foundation`.

## Estado atual

O lote local deixou a PWA operacional para o núcleo de lojas, eventos, cards,
links públicos, solicitações de presença, revisão e convites. O Telegram legado
continua intacto e o schema `pwa_v2` permanece separado e vazio após o reset
local. Não existe autorização para apontar produção para este código.

## Evidências concluídas

- worktree original preservado e branch de migração isolada;
- 31 testes Python aprovados nesta revisão, além de compilação sintática em cache
  temporário;
- typecheck e build React aprovados;
- schema local com RLS/FORCE RLS, grants e lint sem erro;
- smoke integrado local de Auth/API/repository/Storage executado antes deste lote;
- painel visual conferido em desktop e mobile com mocks, sem homologação externa.

## Gates ainda abertos

1. Revisar e aprovar variáveis do ambiente remoto sem expor service role ou
   pepper no navegador.
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

Até todos os gates acima estarem registrados, `PWA_ENABLED` pode permanecer
desligada no ambiente operacional e `TELEGRAM_MUTATIONS_TO_PWA` deve permanecer
desligada. Push, workflow, deploy, migration remota e publicação no Instagram
são marcos independentes e não estão implícitos neste commit.
