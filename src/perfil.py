from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.sheets import buscar_membro

async def mostrar_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if not membro:
        await query.edit_message_text(
            "Cadastro não encontrado. Envie /start para se cadastrar."
        )
        return

    texto = (
        f"👤 *Seu cadastro*\n\n"
        f"Nome: {membro.get('Nome', '')}\n"
        f"Loja: {membro.get('Loja', '')}\n"
        f"Grau: {membro.get('Grau', '')}\n"
        f"Oriente: {membro.get('Oriente', '')}\n"
        f"Potência: {membro.get('Potência', '')}\n"
    )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")]
    ])

    await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)
