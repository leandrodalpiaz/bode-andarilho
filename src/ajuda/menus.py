from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from src.ajuda.faq import mostrar_faq
from src.ajuda.glossario import mostrar_glossario
from src.ajuda.nivel1 import (
	ajuda_nivel1_cancelar,
	ajuda_nivel1_confirmar,
	ajuda_nivel1_filtros,
	ajuda_nivel1_minhas,
	ajuda_nivel1_notificacoes,
	guia_nivel1,
)
from src.ajuda.nivel2 import (
	ajuda_nivel2_cadastrar_loja,
	ajuda_nivel2_copiar_lista,
	ajuda_nivel2_criar_sessao,
	ajuda_nivel2_gerenciar_eventos,
	ajuda_nivel2_notificacoes,
	ajuda_nivel2_ver_confirmados,
	guia_nivel2,
)
from src.ajuda.nivel3 import (
	ajuda_nivel3_editar_membros,
	ajuda_nivel3_gerenciar_permissoes,
	ajuda_nivel3_promover_rebaixar,
	ajuda_nivel3_ver_membros,
	guia_nivel3,
)
from src.ajuda.sobre import mostrar_sobre
from src.ajuda.tutoriais import menu_tutoriais
from src.bot import navegar_para
from src.messages import TEXTO_MENU_AJUDA_PRINCIPAL
from src.permissoes import get_nivel


async def menu_ajuda_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
	texto = TEXTO_MENU_AJUDA_PRINCIPAL
	teclado = InlineKeyboardMarkup(
		[
			[InlineKeyboardButton("📘 Guia rápido", callback_data="ajuda_guia")],
			[InlineKeyboardButton("📚 Tutoriais", callback_data="ajuda_tutoriais")],
			[InlineKeyboardButton("❓ Perguntas frequentes", callback_data="ajuda_faq")],
			[InlineKeyboardButton("📖 Glossário", callback_data="ajuda_glossario")],
			[InlineKeyboardButton("🏛️ Sobre o Bode", callback_data="ajuda_sobre")],
			[InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")],
		]
	)

	await navegar_para(update, context, "Central de Ajuda", texto, teclado)


async def ajuda_guia(update: Update, context: ContextTypes.DEFAULT_TYPE):
	"""Redireciona para o guia adequado ao nível do usuário."""
	user_id = update.effective_user.id
	nivel = get_nivel(user_id)

	if nivel == "1":
		await guia_nivel1(update, context)
	elif nivel == "2":
		await guia_nivel2(update, context)
	else:
		await guia_nivel3(update, context)


ajuda_handlers = [
	CallbackQueryHandler(menu_ajuda_principal, pattern=r"^menu_ajuda$"),
	CallbackQueryHandler(ajuda_guia, pattern=r"^ajuda_guia$"),
	CallbackQueryHandler(menu_tutoriais, pattern=r"^ajuda_tutoriais$"),
	CallbackQueryHandler(mostrar_faq, pattern=r"^ajuda_faq$"),
	CallbackQueryHandler(mostrar_glossario, pattern=r"^ajuda_glossario$"),
	CallbackQueryHandler(mostrar_sobre, pattern=r"^ajuda_sobre$"),
	CallbackQueryHandler(ajuda_nivel1_confirmar, pattern=r"^ajuda_nivel1_confirmar$"),
	CallbackQueryHandler(ajuda_nivel1_cancelar, pattern=r"^ajuda_nivel1_cancelar$"),
	CallbackQueryHandler(ajuda_nivel1_minhas, pattern=r"^ajuda_nivel1_minhas$"),
	CallbackQueryHandler(ajuda_nivel1_notificacoes, pattern=r"^ajuda_nivel1_notificacoes$"),
	CallbackQueryHandler(ajuda_nivel1_filtros, pattern=r"^ajuda_nivel1_filtros$"),
	CallbackQueryHandler(ajuda_nivel2_cadastrar_loja, pattern=r"^ajuda_nivel2_cadastrar_loja$"),
	CallbackQueryHandler(ajuda_nivel2_criar_sessao, pattern=r"^ajuda_nivel2_criar_sessao$"),
	CallbackQueryHandler(ajuda_nivel2_gerenciar_eventos, pattern=r"^ajuda_nivel2_gerenciar_eventos$"),
	CallbackQueryHandler(ajuda_nivel2_ver_confirmados, pattern=r"^ajuda_nivel2_ver_confirmados$"),
	CallbackQueryHandler(ajuda_nivel2_copiar_lista, pattern=r"^ajuda_nivel2_copiar_lista$"),
	CallbackQueryHandler(ajuda_nivel2_notificacoes, pattern=r"^ajuda_nivel2_notificacoes$"),
	CallbackQueryHandler(ajuda_nivel3_promover_rebaixar, pattern=r"^ajuda_nivel3_promover_rebaixar$"),
	CallbackQueryHandler(ajuda_nivel3_editar_membros, pattern=r"^ajuda_nivel3_editar_membros$"),
	CallbackQueryHandler(ajuda_nivel3_ver_membros, pattern=r"^ajuda_nivel3_ver_membros$"),
	CallbackQueryHandler(ajuda_nivel3_gerenciar_permissoes, pattern=r"^ajuda_nivel3_gerenciar_permissoes$"),
]
