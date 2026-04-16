# Fluxos Atualizados do Bode Andarilho (2026-04-01)

Este documento complementa `docs/documentacao_tecnica.md` com os fluxos que estão ativos no código atual e que impactam diretamente navegação, onboarding e suporte com IA.

## Escopo validado no código

Arquivos conferidos:

- `main.py`
- `src/bot.py`
- `src/miniapp.py`
- `src/eventos.py`
- `src/eventos_secretario.py`
- `src/cadastro_evento.py`
- `src/scheduler.py`
- `src/membro_lembretes.py`
- `src/ajuda/*.py`

## Novidades de fluxo que já estão em produção

1. Onboarding de grupo para privado com fallback

- O bot responde a `bode`, `menu` e `painel` no grupo.
- Se o privado estiver disponível, abre fluxo no privado.
- Se o privado não estiver disponível, envia fallback no grupo com botão de deep link.
- Entrada e saída de membro no grupo atualizam status de cadastro (ativo/inativo).

1. Verificação de participação no grupo antes de liberar painel

- Antes de montar painel no privado, o bot valida se o usuário ainda está no grupo principal.
- Se não estiver, bloqueia acesso e orienta retorno ao grupo.

1. Fluxo híbrido com Telegram Mini App

- Cadastro de membro, loja e evento pode ser feito por formulario web.
- Fluxo possui rascunho + confirmação por callback (`draft_*`).
- Cadastro via mini app valida `initData` assinado do Telegram.
- `telegram_id` vem apenas do `initData` validado.

1. Cadastro e publicação de evento com sincronização de card no grupo

- Evento pode ser criado por fluxo conversacional ou mini app.
- Publicação no grupo grava `Telegram Message ID do grupo` para sincronizações futuras.
- Edições/cancelamentos/refazer evento sincronizam card de grupo quando possível.

1. Confirmação com opção de ágape

- Teclado de confirmação varia conforme tipo de ágape do evento:

  - com ágape gratuito
  - com ágape pago
  - com ágape genérico
  - sem ágape (confirmação simples)

1. Janela de silêncio para notificações do secretário

- Confirmações feitas entre 22:00 e 07:00 são acumuladas.
- Resumo consolidado é enviado fora da janela de silêncio.
- Job dedicado no scheduler faz flush diário às 07:00.

1. Lembretes do próprio membro no menu principal

- Menu principal possui `Meus Lembretes`.
- Membro ativa/desativa lembretes privados sem depender do secretário.

1. Assistente IA inicial com guardrails

- Comandos: `/ia` e `/assistente`.
- Classificação de intenção baseada em `docs/ajuda_ia_base.yaml`.
- IA apenas sugere fluxo e aciona callbacks existentes (não executa ação administrativa direta).
- Criação de sessão por linguagem natural para níveis 2 e 3:

  - entende pedido livre como "sessão de aprendiz sexta às 20h"
  - monta rascunho parcial ou completo
  - se faltar dado, entra em complemento multi-turno
  - exige confirmação final antes de publicar

- Regra de loja na criação por IA:

  - secretário: usa automaticamente a loja vinculada ao perfil
  - admin: usa a loja da frase quando existir; se não existir, solicita a loja do evento

- Bloqueios explícitos para:

  - dados pessoais de terceiros
  - informação técnica sensível (tokens, secrets, credenciais)
  - tentativas de bypass de permissões administrativas

1. Painel de observabilidade da IA (agregado)

- Comandos: `/ia_stats` e `/assistente_stats`.
- Acesso restrito a administrador (nivel 3).
- Exibe métricas agregadas de 24h e 7d:

  - total de interações
  - taxa de intenção reconhecida
  - bloqueios de segurança
  - não reconhecidas
  - top intenções
  - top motivos de bloqueio

- Não exibe texto bruto do usuário nem dados pessoais.

1. Relatório de aprendizado operacional da IA

- Comandos: `/ia_relatorio` e `/assistente_relatorio`.
- Acesso restrito a administrador (nivel 3).
- Agrupa temas não reconhecidos usando `topic_hint` seguro, sem guardar frase original.
- Sugere melhorias de:

  - novas intenções/gatilhos
  - FAQ e tutoriais
  - destaque de UX para funções muito procuradas

- Toda mudança continua dependente de aprovação humana.

1. UX sem barra (comando como fallback)

- Menu principal agora inclui botão `Assistente IA`.
- No privado, texto livre (sem `/ia`) é encaminhado ao assistente quando não houver fluxo formal ativo.
- No privado, as palavras `menu`, `painel` e `bode` reconstroem o painel principal sem precisar `/start`.
- Admin pode acionar métricas e relatório da IA também por linguagem natural no privado:

  - "metricas ia"
  - "relatorio ia"

- Comandos com `/` continuam ativos apenas como plano B técnico.

## Registro de handlers (estado atual)

Principais grupos no `register_handlers(app)`:

- Conversation handlers:

  - confirmação de presença
  - cadastro de evento
  - promover/rebaixar/editar membro
  - editar perfil
  - editar evento do secretário
  - cadastro de loja

- Command handlers:

  - `/start`
  - `/ping`

- Callbacks de ajuda:

  - via `src/ajuda/menus.py`

- Callbacks híbridos do mini app:

  - `draft_membro_*`
  - `draft_loja_*`
  - `draft_evento_*`

- Handlers de grupo:

  - `ChatMemberHandler(novo_membro_grupo_handler)`
  - `MessageHandler` para palavra-chave de entrada (`bode|menu|painel`)
  - `MessageHandler` para texto e comandos no grupo

## Scheduler (estado atual)

Jobs ativos em `src/scheduler.py`:

- `job_lembretes_24h` - diário 08:00
- `job_lembretes_meio_dia` - diário 12:00
- `job_celebracao_mensal` - dia 1 às 09:00
- `job_flush_notificacoes_secretario` - diário 07:00

## Ajuda atual e lacunas

Situação atual:

- `src/ajuda/faq.py`, `nivel1.py`, `nivel2.py`, `nivel3.py`, `glossario.py` ativos.
- `src/ajuda/tutoriais.py` agora contém tutoriais navegáveis por tema.

Lacuna principal:

- Ainda vale ampliar os tutoriais conforme surgirem dúvidas reais do piloto.

## Recomendação para IA

Para evitar respostas inventadas:

- IA deve consultar uma base estruturada por intenção.
- Cada intenção precisa apontar para ação real de sistema (callback/fluxo).
- Respostas devem ser curtas, com tom fraterno, sem autonomia administrativa.

Base proposta:

- `docs/ajuda_ia_base.yaml`
