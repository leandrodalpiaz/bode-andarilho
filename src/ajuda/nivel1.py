from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_GUIA_MEMBRO


async def guia_nivel1(update, context):
	texto = TEXTO_GUIA_MEMBRO + "\n\n"
	texto += "*1. Ver Sessões Agendadas:*\n"
	texto += "   Acesse o menu principal e clique em '📅 Ver Sessões Agendadas'. Você pode filtrar por semana, mês ou todos os eventos.\n\n"
	texto += "*2. Confirmar Presença:*\n"
	texto += "   Nos detalhes de um evento, clique em '✅ Confirmar presença'. Se houver ágape, escolha '🍽 Participar com ágape' ou '🚫 Participar sem ágape'.\n\n"
	texto += "*3. Minhas Visitações:*\n"
	texto += "   No menu principal, clique em '✅ Minhas Visitações' para ver os eventos futuros que você confirmou e seu histórico de participação.\n\n"
	texto += "*4. Meu Perfil / Dados:*\n"
	texto += "   Acesse '👤 Meu Perfil / Dados' para visualizar e editar suas informações de cadastro (nome, grau, loja, etc.).\n\n"
	texto += "*5. Cancelar Presença:*\n"
	texto += "   Você pode cancelar sua presença pelos detalhes da confirmação, pela lista de confirmados do evento ou pela mensagem de confirmação no privado."

	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("✅ Confirmar presença", callback_data="ajuda_nivel1_confirmar")],
			[InlineKeyboardButton("❌ Cancelar presença", callback_data="ajuda_nivel1_cancelar")],
			[InlineKeyboardButton("📋 Minhas visitações", callback_data="ajuda_nivel1_minhas")],
			[InlineKeyboardButton("🔔 Sobre notificações", callback_data="ajuda_nivel1_notificacoes")],
			[InlineKeyboardButton("📅 Como usar os filtros", callback_data="ajuda_nivel1_filtros")],
			[InlineKeyboardButton("🔙 Voltar à Central de Ajuda", callback_data="menu_ajuda")],
		]
	)

	await navegar_para(update, context, "Guia do Membro", texto, teclado)


async def ajuda_nivel1_confirmar(update, context):
	texto = (
		"*Como Confirmar Presença:*\n\n"
		"1. No menu principal, clique em '📅 Ver Sessões Agendadas'.\n"
		"2. Escolha o evento desejado na lista.\n"
		"3. Nos detalhes do evento, clique em '✅ Confirmar presença'.\n"
		"4. Se houver ágape, o bot perguntará se você deseja participar com ou sem ágape. Escolha a opção desejada.\n"
		"5. Você receberá uma mensagem de confirmação no seu privado."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Confirmar Presença", texto, teclado)


async def ajuda_nivel1_cancelar(update, context):
	texto = (
		"*Como Cancelar Presença:*\n\n"
		"Você pode cancelar sua presença de três formas:\n"
		"1. *Pelos detalhes da confirmação:* Vá em '✅ Minhas Visitações' > '📅 Próximos eventos', escolha o evento e clique em '❌ Cancelar presença'.\n"
		"2. *Pela lista de confirmados:* Nos detalhes do evento, clique em '👥 Ver confirmados'. Se você estiver na lista, clique em '❌ Cancelar minha presença'.\n"
		"3. *Pela mensagem de confirmação no privado:* A mensagem que você recebeu quando confirmou tem um botão de cancelar.\n\n"
		"O bot sempre pedirá uma confirmação final."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Cancelar Presença", texto, teclado)


async def ajuda_nivel1_minhas(update, context):
	texto = (
		"*Minhas Visitações:*\n\n"
		"No menu principal, clique em '✅ Minhas Visitações'.\n"
		"Você verá duas opções:\n"
		" - *'📅 Próximos eventos':* Lista os eventos futuros para os quais você confirmou presença.\n"
		" - *'📜 Histórico':* Mostra todos os eventos passados que você participou."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Minhas Visitações", texto, teclado)


async def ajuda_nivel1_notificacoes(update, context):
	texto = (
		"*Sobre Notificações:*\n\n"
		"O Bode Andarilho envia lembretes automáticos para os eventos que você confirmou:\n"
		" - *24 horas antes:* Um lembrete na véspera da sessão.\n"
		" - *Ao meio-dia do evento:* O tradicional 'MEIO DIA EM PONTO!' para lembrar que hoje tem sessão.\n\n"
		"Esses lembretes são enviados no seu privado para garantir que você não perca a sessão."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Sobre Notificações", texto, teclado)


async def ajuda_nivel1_filtros(update, context):
	texto = (
		"*Como Usar os Filtros de Eventos:*\n\n"
		"Ao acessar '📅 Ver Sessões Agendadas', você encontrará botões para filtrar os eventos:\n"
		" - *'Esta semana':* Mostra os eventos agendados para os próximos 7 dias.\n"
		" - *'Este mês':* Mostra os eventos agendados para o mês corrente.\n"
		" - *'Todos':* Mostra todos os eventos futuros cadastrados.\n\n"
		"Use os filtros para encontrar as sessões que mais lhe interessam."
	)
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar ao Guia do Membro", callback_data="ajuda_guia")]]
	)
	await navegar_para(update, context, "Filtros de Eventos", texto, teclado)
