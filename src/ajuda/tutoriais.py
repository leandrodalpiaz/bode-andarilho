from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_TUTORIAIS_INICIAL


_TUTORIAIS = {
	"onboarding": {
		"titulo": "Tutorial: Comecar no bot",
		"texto": (
			"*Como comecar no Bode Andarilho*\n\n"
			"1. No grupo, use `bode`, `menu` ou `painel`.\n"
			"2. O bot direciona para o privado.\n"
			"3. No privado, use /start e siga o menu.\n"
			"4. Se o privado falhar, use o botao de abrir privado enviado no grupo.\n\n"
			"*Dica:* o painel depende de participacao ativa no grupo principal."
		),
	},
	"confirmacao_agape": {
		"titulo": "Tutorial: Confirmar presenca e agape",
		"texto": (
			"*Como confirmar presenca corretamente*\n\n"
			"1. Abra `Ver Sessoes`.\n"
			"2. Entre no evento desejado.\n"
			"3. Escolha a opcao disponivel:\n"
			"- Com agape (gratuito/pago), quando houver.\n"
			"- Sem agape, quando preferir.\n"
			"4. O bot envia confirmacao no privado.\n\n"
			"Para mudar opcao de agape, cancele e confirme novamente."
		),
	},
	"minhas_confirmacoes": {
		"titulo": "Tutorial: Minhas confirmacoes",
		"texto": (
			"*Como acompanhar suas presencas*\n\n"
			"1. Abra `Minhas Presencas`.\n"
			"2. Use `Proximas sessoes` para compromissos futuros.\n"
			"3. Use `Historico` para sessoes ja realizadas.\n"
			"4. Se necessario, cancele presenca pelo fluxo oficial."
		),
	},
	"cadastro_evento": {
		"titulo": "Tutorial: Criar sessao com linguagem natural",
		"texto": (
			"*Como criar uma sessao*\n\n"
			"Voce pode criar uma sessao descrevendo de forma simples, como se estivesse falando.\n\n"
			"O bot entende frases naturais e organiza o evento automaticamente.\n\n"
			"*Sessoes economicas por grau*\n\n"
			"*Aprendiz (1o grau)*\n"
			"• Sessao de aprendiz dia 15/11 as 20h\n"
			"• Sessao economica de 1o grau dia 10/12 as 19h30\n"
			"• Sessao grau 1 sexta as 20h\n\n"
			"*Companheiro (2o grau)*\n"
			"• Sessao de companheiro dia 22/11 as 20h\n"
			"• Sessao economica de 2o grau com agape\n"
			"• Sessao grau 2 amanha as 20h\n\n"
			"*Mestre (3o grau)*\n"
			"• Sessao de mestre dia 05/12 as 20h\n"
			"• Sessao economica de 3o grau com agape pago\n"
			"• Sessao grau 3 sexta as 20h\n\n"
			"*Sessoes com agape*\n\n"
			"• Sessao de aprendiz dia 15/11 as 20h com agape\n"
			"• Sessao de companheiro com agape pago\n"
			"• Sessao de mestre sexta as 20h com agape livre\n\n"
			"*Sessoes magnas*\n\n"
			"• Sessao magna de iniciacao dia 10/01 as 20h\n"
			"• Sessao magna de elevacao dia 15/11 as 20h\n"
			"• Sessao magna de exaltacao sexta as 20h\n"
			"• Sessao magna de instalacao dia 05/12 as 19h\n\n"
			"*Sessoes magnas com nomes*\n\n"
			"Se voce incluir nomes, o bot coloca automaticamente como observacao ou ordem do dia.\n"
			"• Sessao magna de iniciacao do Joao e Pedro dia 10/01 as 20h\n"
			"• Iniciacao dos profanos Carlos e Andre dia 15/12 as 20h\n"
			"• Sessao magna de elevacao do irmao Jose dia 20/11 as 20h\n\n"
			"*Exemplos livres*\n\n"
			"• Sessao dia 15/11 aprendiz as 20h\n"
			"• Sessao sexta companheiro com agape pago\n"
			"• Criar sessao de mestre amanha as 20h\n"
			"• Sessao amanha as 20h\n\n"
			"*Se faltar informacao*\n\n"
			"Se faltar data, horario, grau ou outro dado, o bot pergunta apenas o necessario para completar.\n\n"
			"*Regra de loja*\n\n"
			"• Secretario: a loja vinculada ao perfil e usada automaticamente na IA.\n"
			"• Admin: se a frase nao trouxer loja, o bot vai pedir a loja do evento."
		),
	},
	"miniapp_rascunho": {
		"titulo": "Tutorial: Mini App e rascunhos",
		"texto": (
			"*Como funciona o fluxo hibrido com Mini App*\n\n"
			"1. Abra formulario web de membro, loja ou evento quando esse fluxo estiver disponivel para o seu perfil.\n"
			"2. Envie os dados para salvar rascunho.\n"
			"3. Revise o resumo no chat.\n"
			"4. Confirme no bot pelos botoes `draft_*`.\n\n"
			"No cadastro de evento, o Mini App e mantido para secretario. Administrador segue o fluxo guiado do bot para esse ponto."
		),
	},
	"notificacoes_silencio": {
		"titulo": "Tutorial: Notificacoes e janela de silencio",
		"texto": (
			"*Como as notificacoes do secretario funcionam*\n\n"
			"1. Ative/desative em `Configurar notificacoes`.\n"
			"2. Confirmacoes entre 22:00 e 07:00 sao acumuladas.\n"
			"3. Um resumo consolidado e enviado apos a janela de silencio.\n\n"
			"Assim o bot reduz ruido de madrugada sem perder informacoes."
		),
	},
}


async def menu_tutoriais(update, context):
	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("1) Comecar no bot (grupo e privado)", callback_data="ajuda_tutorial|onboarding")],
			[InlineKeyboardButton("2) Confirmar presenca com ou sem agape", callback_data="ajuda_tutorial|confirmacao_agape")],
			[InlineKeyboardButton("3) Minhas confirmacoes e historico", callback_data="ajuda_tutorial|minhas_confirmacoes")],
			[InlineKeyboardButton("4) Criar sessao com linguagem natural", callback_data="ajuda_tutorial|cadastro_evento")],
			[InlineKeyboardButton("5) Mini App: rascunho e confirmacao", callback_data="ajuda_tutorial|miniapp_rascunho")],
			[InlineKeyboardButton("6) Notificacoes e janela de silencio", callback_data="ajuda_tutorial|notificacoes_silencio")],
			[InlineKeyboardButton("Voltar a Central de Ajuda", callback_data="menu_ajuda")],
		]
	)

	await navegar_para(update, context, "Tutoriais", TEXTO_TUTORIAIS_INICIAL, teclado)


async def mostrar_tutorial(update, context):
	query = update.callback_query
	chave = ""
	if query and query.data and "|" in query.data:
		_, chave = query.data.split("|", 1)

	item = _TUTORIAIS.get(chave)
	if not item:
		await menu_tutoriais(update, context)
		return

	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("Voltar aos Tutoriais", callback_data="ajuda_tutoriais")],
			[InlineKeyboardButton("Voltar a Central de Ajuda", callback_data="menu_ajuda")],
		]
	)
	await navegar_para(update, context, item["titulo"], item["texto"], teclado)
