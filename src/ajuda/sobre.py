from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import navegar_para
from src.messages import TEXTO_SOBRE_BODE


async def mostrar_sobre(update, context):
	teclado = InlineKeyboardMarkup(
		[[InlineKeyboardButton("🔙 Voltar à Central de Ajuda", callback_data="menu_ajuda")]]
	)

	await navegar_para(update, context, "Sobre o Bode", TEXTO_SOBRE_BODE, teclado)
