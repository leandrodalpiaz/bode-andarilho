from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from src.eventos import mostrar_eventos, mostrar_detalhes_evento, confirmar_presenca, cancelar_presenca
from src.perfil import mostrar_perfil

def menu_principal_teclado():
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Ver eventos", callback_data="ver_eventos")],
        [InlineKeyboardButton("👤 Meu cadastro", callback_data="meu_cadastro")],
    ])
    return teclado

async def botao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "ver_eventos":
        await mostrar_eventos(update, context)
    elif data.startswith("evento_"):
        await mostrar_detalhes_evento(update, context)
    elif data.startswith("confirmar_"):
        await confirmar_presenca(update, context)
    elif data.startswith("cancelar_"):
        await cancelar_presenca(update, context)
    elif data == "meu_cadastro":
        await mostrar_perfil(update, context)
    elif data == "menu_principal":
        await query.edit_message_text(
            "O que deseja fazer?",
            reply_markup=menu_principal_teclado()
        )
    else:
        await query.answer("Função em desenvolvimento.")
