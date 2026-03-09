from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_TUTORIAIS_INICIAL


async def menu_tutoriais(update, context):
	# Placeholder inicial; conteúdos detalhados serão adicionados futuramente.
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar à Central de Ajuda", callback_data="menu_ajuda")]]
	)

	await navegar_para(update, context, "Tutoriais", TEXTO_TUTORIAIS_INICIAL, teclado)
