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
		"titulo": "Tutorial: Cadastrar e publicar sessao",
		"texto": (
			"*Fluxo do secretario para nova sessao*\n\n"
			"1. Abra `Painel do Secretario`.\n"
			"2. Use `Cadastrar evento`.\n"
			"3. Preencha data, hora, grau, tipo, traje, agape e observacoes.\n"
			"4. Revise e confirme publicacao.\n"
			"5. O bot publica no grupo e sincroniza o card quando houver edicao."
		),
	},
	"miniapp_rascunho": {
		"titulo": "Tutorial: Mini App e rascunhos",
		"texto": (
			"*Como funciona o fluxo hibrido com Mini App*\n\n"
			"1. Abra formulario web de membro, loja ou evento.\n"
			"2. Envie os dados para salvar rascunho.\n"
			"3. Revise o resumo no chat.\n"
			"4. Confirme no bot pelos botoes `draft_*`.\n\n"
			"O cadastro/publicacao so conclui apos confirmacao final no fluxo oficial."
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
			[InlineKeyboardButton("4) Cadastrar e publicar sessao (secretario)", callback_data="ajuda_tutorial|cadastro_evento")],
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
