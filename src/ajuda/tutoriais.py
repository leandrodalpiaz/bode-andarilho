from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_TUTORIAIS_INICIAL


_TUTORIAIS = {
	"onboarding": {
		"titulo": "Tutorial: Começar no bot",
		"texto": (
			"*Como começar no Bode Andarilho*\n\n"
			"1. No grupo, use `bode`, `menu` ou `painel`.\n"
			"2. O bot direciona para o privado.\n"
			"3. No privado, use /start e siga o menu.\n"
			"4. Se o privado falhar, use o botão de abrir privado enviado no grupo.\n\n"
			"*Dica:* o painel depende de participação ativa no grupo principal."
		),
	},
	"confirmacao_agape": {
		"titulo": "Tutorial: Confirmar presença e ágape",
		"texto": (
			"*Como confirmar presença corretamente*\n\n"
			"1. Abra `Ver Sessões`.\n"
			"2. Entre no evento desejado.\n"
			"3. Escolha a opção disponível:\n"
			"- Com ágape (gratuito/pago), quando houver.\n"
			"- Sem ágape, quando preferir.\n"
			"4. O bot envia confirmação no privado.\n\n"
			"Para mudar a opção de ágape, cancele e confirme novamente."
		),
	},
	"minhas_confirmacoes": {
		"titulo": "Tutorial: Minhas confirmações",
		"texto": (
			"*Como acompanhar suas presenças*\n\n"
			"1. Abra `Minhas Presenças`.\n"
			"2. Use `Próximas sessões` para compromissos futuros.\n"
			"3. Use `Histórico` para sessões já realizadas.\n"
			"4. Se necessário, cancele a presença pelo fluxo oficial."
		),
	},
	"cadastro_evento": {
		"titulo": "Tutorial: Criar sessão com linguagem natural",
		"texto": (
			"*Como criar uma sessão*\n\n"
			"Você pode criar uma sessão descrevendo de forma simples, como se estivesse falando.\n\n"
			"O bot entende frases naturais e organiza o evento automaticamente.\n\n"
			"*Sessões econômicas por grau*\n\n"
			"*Aprendiz (1o grau)*\n"
			"• Sessão de aprendiz dia 15/11 às 20h\n"
			"• Sessão econômica de 1o grau dia 10/12 às 19h30\n"
			"• Sessão grau 1 sexta às 20h\n\n"
			"*Companheiro (2o grau)*\n"
			"• Sessão de companheiro dia 22/11 às 20h\n"
			"• Sessão econômica de 2o grau com ágape\n"
			"• Sessão grau 2 amanhã às 20h\n\n"
			"*Mestre (3o grau)*\n"
			"• Sessão de mestre dia 05/12 às 20h\n"
			"• Sessão econômica de 3o grau com ágape pago\n"
			"• Sessão grau 3 sexta às 20h\n\n"
			"*Sessões com ágape*\n\n"
			"• Sessão de aprendiz dia 15/11 às 20h com ágape\n"
			"• Sessão de companheiro com ágape pago\n"
			"• Sessão de mestre sexta às 20h com ágape livre\n\n"
			"*Sessões magnas*\n\n"
			"• Sessão magna de iniciação dia 10/01 às 20h\n"
			"• Sessão magna de elevação dia 15/11 às 20h\n"
			"• Sessão magna de exaltação sexta às 20h\n"
			"• Sessão magna de instalação dia 05/12 às 19h\n\n"
			"*Sessões magnas com nomes*\n\n"
			"Se você incluir nomes, o bot coloca automaticamente como observação ou ordem do dia.\n"
			"• Sessão magna de iniciação do João e Pedro dia 10/01 às 20h\n"
			"• Iniciação dos profanos Carlos e André dia 15/12 às 20h\n"
			"• Sessão magna de elevação do irmão José dia 20/11 às 20h\n\n"
			"*Exemplos livres*\n\n"
			"• Sessão dia 15/11 aprendiz às 20h\n"
			"• Sessão sexta companheiro com ágape pago\n"
			"• Criar sessão de mestre amanhã às 20h\n"
			"• Sessão amanhã às 20h\n\n"
			"*Se faltar informação*\n\n"
			"Se faltar data, horário, grau ou outro dado, o bot pergunta apenas o necessário para completar.\n\n"
			"*Regra de loja*\n\n"
			"• Secretário: a loja vinculada ao perfil é usada automaticamente na IA.\n"
			"• Admin: se a frase não trouxer loja, o bot vai pedir a loja do evento."
		),
	},
	"miniapp_rascunho": {
		"titulo": "Tutorial: Mini App e rascunhos",
		"texto": (
			"*Como funciona o fluxo híbrido com Mini App*\n\n"
			"1. Abra formulário web de membro, loja ou evento quando esse fluxo estiver disponível para o seu perfil.\n"
			"2. Envie os dados para salvar rascunho.\n"
			"3. Revise o resumo no chat.\n"
			"4. Confirme no bot pelos botões `draft_*`.\n\n"
			"No cadastro de evento, o Mini App é mantido para secretário. Administrador segue o fluxo guiado do bot para esse ponto."
		),
	},
	"notificacoes_silencio": {
		"titulo": "Tutorial: Notificações e janela de silêncio",
		"texto": (
			"*Como as notificações do secretário funcionam*\n\n"
			"1. Ative/desative em `Configurar notificações`.\n"
			"2. Confirmações entre 22:00 e 07:00 são acumuladas.\n"
			"3. Um resumo consolidado é enviado após a janela de silêncio.\n\n"
			"Assim o bot reduz ruído de madrugada sem perder informações."
		),
	},
}


async def menu_tutoriais(update, context):
	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("1) Começar no bot (grupo e privado)", callback_data="ajuda_tutorial|onboarding")],
			[InlineKeyboardButton("2) Confirmar presença com ou sem ágape", callback_data="ajuda_tutorial|confirmacao_agape")],
			[InlineKeyboardButton("3) Minhas confirmações e histórico", callback_data="ajuda_tutorial|minhas_confirmacoes")],
			[InlineKeyboardButton("4) Criar sessão com linguagem natural", callback_data="ajuda_tutorial|cadastro_evento")],
			[InlineKeyboardButton("5) Mini App: rascunho e confirmação", callback_data="ajuda_tutorial|miniapp_rascunho")],
			[InlineKeyboardButton("6) Notificações e janela de silêncio", callback_data="ajuda_tutorial|notificacoes_silencio")],
			[InlineKeyboardButton("Voltar à Central de Ajuda", callback_data="menu_ajuda")],
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
			[InlineKeyboardButton("Voltar à Central de Ajuda", callback_data="menu_ajuda")],
		]
	)
	await navegar_para(update, context, item["titulo"], item["texto"], teclado)
