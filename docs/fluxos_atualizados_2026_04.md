# Fluxos Atualizados do Bode Andarilho (2026-04-01)

Este documento complementa `docs/documentacao_tecnica.md` com os fluxos que estao ativos no codigo atual e que impactam diretamente navegacao, onboarding e suporte com IA.

## Escopo validado no codigo

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

## Novidades de fluxo que ja estao em producao

1. Onboarding de grupo para privado com fallback
- O bot responde a `bode`, `menu` e `painel` no grupo.
- Se o privado estiver disponivel, abre fluxo no privado.
- Se o privado nao estiver disponivel, envia fallback no grupo com botao de deep link.
- Entrada e saida de membro no grupo atualizam status de cadastro (ativo/inativo).

2. Verificacao de participacao no grupo antes de liberar painel
- Antes de montar painel no privado, o bot valida se o usuario ainda esta no grupo principal.
- Se nao estiver, bloqueia acesso e orienta retorno ao grupo.

3. Fluxo hibrido com Telegram Mini App
- Cadastro de membro, loja e evento pode ser feito por formulario web.
- Fluxo possui rascunho + confirmacao por callback (`draft_*`).
- Cadastro via mini app valida `initData` assinado do Telegram.
- `telegram_id` vem apenas do `initData` validado.

4. Cadastro e publicacao de evento com sincronizacao de card no grupo
- Evento pode ser criado por fluxo conversacional ou mini app.
- Publicacao no grupo grava `Telegram Message ID do grupo` para sincronizacoes futuras.
- Edicoes/cancelamentos/refazer evento sincronizam card de grupo quando possivel.

5. Confirmacao com opcao de agape
- Teclado de confirmacao varia conforme tipo de agape do evento:
  - com agape gratuito
  - com agape pago
  - com agape generico
  - sem agape (confirmacao simples)

6. Janela de silencio para notificacoes do secretario
- Confirmacoes feitas entre 22:00 e 07:00 sao acumuladas.
- Resumo consolidado e enviado fora da janela de silencio.
- Job dedicado no scheduler faz flush diario as 07:00.

7. Lembretes do proprio membro no menu principal
- Menu principal possui `Meus Lembretes`.
- Membro ativa/desativa lembretes privados sem depender do secretario.

8. Assistente IA inicial com guardrails
- Comandos: `/ia` e `/assistente`.
- Classificacao de intencao baseada em `docs/ajuda_ia_base.yaml`.
- IA apenas sugere fluxo e aciona callbacks existentes (nao executa acao administrativa direta).
- Bloqueios explicitos para:
  - dados pessoais de terceiros
  - informacao tecnica sensivel (tokens, secrets, credenciais)
  - tentativas de bypass de permissoes administrativas

9. Painel de observabilidade da IA (agregado)
- Comandos: `/ia_stats` e `/assistente_stats`.
- Acesso restrito a administrador (nivel 3).
- Exibe metricas agregadas de 24h e 7d:
  - total de interacoes
  - taxa de intencao reconhecida
  - bloqueios de seguranca
  - nao reconhecidas
  - top intencoes
  - top motivos de bloqueio
- Nao exibe texto bruto do usuario nem dados pessoais.

10. Relatorio de aprendizado operacional da IA
- Comandos: `/ia_relatorio` e `/assistente_relatorio`.
- Acesso restrito a administrador (nivel 3).
- Agrupa temas nao reconhecidos usando `topic_hint` seguro, sem guardar frase original.
- Sugere melhorias de:
  - novas intencoes/gatilhos
  - FAQ e tutoriais
  - destaque de UX para funcoes muito procuradas
- Toda mudanca continua dependente de aprovacao humana.

## Registro de handlers (estado atual)

Principais grupos no `register_handlers(app)`:
- Conversation handlers:
  - confirmacao de presenca
  - cadastro de evento
  - promover/rebaixar/editar membro
  - editar perfil
  - editar evento do secretario
  - cadastro de loja
- Command handlers:
  - `/start`
  - `/ping`
- Callbacks de ajuda:
  - via `src/ajuda/menus.py`
- Callbacks hibridos do mini app:
  - `draft_membro_*`
  - `draft_loja_*`
  - `draft_evento_*`
- Handlers de grupo:
  - `ChatMemberHandler(novo_membro_grupo_handler)`
  - `MessageHandler` para palavra-chave de entrada (`bode|menu|painel`)
  - `MessageHandler` para texto e comandos no grupo

## Scheduler (estado atual)

Jobs ativos em `src/scheduler.py`:
- `job_lembretes_24h` - diario 08:00
- `job_lembretes_meio_dia` - diario 12:00
- `job_celebracao_mensal` - dia 1 as 09:00
- `job_flush_notificacoes_secretario` - diario 07:00

## Ajuda atual e lacunas

Situacao atual:
- `src/ajuda/faq.py`, `nivel1.py`, `nivel2.py`, `nivel3.py`, `glossario.py` ativos.
- `src/ajuda/tutoriais.py` agora contem tutoriais navegaveis por tema.

Lacuna principal:
- Ainda vale ampliar os tutoriais conforme surgirem duvidas reais do piloto.

## Recomendacao para IA

Para evitar respostas inventadas:
- IA deve consultar uma base estruturada por intencao.
- Cada intencao precisa apontar para acao real de sistema (callback/fluxo).
- Respostas devem ser curtas, com tom fraterno, sem autonomia administrativa.

Base proposta:
- `docs/ajuda_ia_base.yaml`
