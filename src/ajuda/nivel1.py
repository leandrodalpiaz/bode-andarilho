from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_GUIA_MEMBRO


async def guia_nivel1(update, context):
	texto = TEXTO_GUIA_MEMBRO + "\n\n"
	texto += "*1. Ver Sessões:*\n"
	texto += "   No menu principal, clique em '📅 Ver Sessões'. Você pode consultar o calendário do mês, filtrar por semana, mês, próximos meses ou grau.\n\n"
	texto += "*2. Confirmar presença:*\n"
	texto += "   Nos detalhes da sessão, use '✅ Confirmar presença' ou selecione a opção com ágape quando ela estiver disponível.\n\n"
	texto += "*3. Minhas Presenças:*\n"
	texto += "   Em '✅ Minhas Presenças', você vê suas próximas confirmações e também o histórico das sessões já realizadas.\n\n"
	texto += "*4. Meu Perfil:*\n"
	texto += "   Em '👤 Meu Perfil', você consulta seus dados, vê seu nível de acesso, confere conquistas e pode editar o próprio cadastro.\n\n"
	texto += "*5. Meus Lembretes:*\n"
	texto += "   Em '🔔 Meus Lembretes', você ativa ou desativa os avisos privados que o bot envia antes das sessões confirmadas."

	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("✅ Como confirmar presença", callback_data="ajuda_nivel1_confirmar")],
			[InlineKeyboardButton("❌ Como cancelar presença", callback_data="ajuda_nivel1_cancelar")],
			[InlineKeyboardButton("📋 Minhas presenças", callback_data="ajuda_nivel1_minhas")],
			[InlineKeyboardButton("🔔 Como funcionam os lembretes", callback_data="ajuda_nivel1_notificacoes")],
			[InlineKeyboardButton("📅 Como encontrar sessões", callback_data="ajuda_nivel1_filtros")],
			[InlineKeyboardButton("🔙 Voltar à Ajuda", callback_data="menu_ajuda")],
		]
	)

	await navegar_para(update, context, "Guia do Membro", texto, teclado)


async def ajuda_nivel1_confirmar(update, context):
	texto = (
		"*Como Confirmar Presença:*\n\n"
		"1. No menu principal, clique em '📅 Ver Sessões'.\n"
		"2. Escolha a sessão desejada na lista.\n"
		"3. Nos detalhes, clique em '✅ Confirmar presença' ou escolha a opção com ágape.\n"
		"4. O bot registrará sua confirmação e enviará um aviso no seu privado."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Confirmar Presença", texto, teclado)


async def ajuda_nivel1_cancelar(update, context):
	texto = (
		"*Como Cancelar Presença:*\n\n"
		"Você pode cancelar sua presença de três formas:\n"
		"1. *Pelas próximas confirmações:* vá em '✅ Minhas Presenças' > '📅 Próximas sessões', escolha a sessão e use o botão de cancelar.\n"
		"2. *Pela lista de confirmados:* nos detalhes da sessão, clique em '👥 Ver confirmados' e cancele sua presença se ela estiver registrada.\n"
		"3. *Pela mensagem de confirmação no privado:* a mensagem enviada pelo bot também traz um botão para cancelar.\n\n"
		"O bot sempre pedirá uma confirmação final."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Cancelar Presença", texto, teclado)


async def ajuda_nivel1_minhas(update, context):
	texto = (
		"*Minhas Presenças:*\n\n"
		"No menu principal, clique em '✅ Minhas Presenças'.\n"
		"Você verá duas opções:\n"
		" - *'📅 Próximas sessões':* lista suas confirmações futuras.\n"
		" - *'📜 Histórico':* mostra as sessões passadas em que você participou."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Minhas Presenças", texto, teclado)


async def ajuda_nivel1_notificacoes(update, context):
	texto = (
		"*Como Funcionam os Lembretes:*\n\n"
		"O Bode Andarilho pode enviar lembretes automáticos para as sessões que você confirmou:\n"
		" - *na véspera da sessão*\n"
		" - *ao meio-dia do dia da sessão*\n\n"
		"Você pode ativar ou desativar isso em '🔔 Meus Lembretes' no menu principal."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Lembretes do Membro", texto, teclado)


async def ajuda_nivel1_filtros(update, context):
	texto = (
		"*Como Encontrar Sessões:*\n\n"
		"Ao acessar '📅 Ver Sessões', você verá opções para buscar por:\n"
		" - calendário do mês\n"
		" - esta semana\n"
		" - próxima semana\n"
		" - este mês\n"
		" - próximos meses\n"
		" - grau\n\n"
		"Use o filtro mais rápido para chegar na sessão que deseja."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Como Encontrar Sessões", texto, teclado)
