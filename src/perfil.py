# src/perfil.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.sheets import buscar_membro

async def mostrar_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if membro:
        texto_perfil = (
            f"👤 *Seu Cadastro:*\n"
            f"Nome: {membro.get('Nome', 'N/A')}\n"
            f"Loja: {membro.get('Loja', 'N/A')}\n"
            f"Grau: {membro.get('Grau', 'N/A')}\n"
            f"Oriente: {membro.get('Oriente', 'N/A')}\n"
            f"Potência: {membro.get('Potência', 'N/A')}\n"
            f"Telefone: {membro.get('Telefone', 'N/A')}\n"
            f"Nível: {membro.get('Nivel', 'membro')}\n"
        )
        # Botão para editar
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Editar dados", callback_data="editar_perfil")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")]
        ])
        await query.edit_message_text(texto_perfil, parse_mode="Markdown", reply_markup=teclado)
    else:
        await query.edit_message_text("Seu cadastro não foi encontrado. Envie /start para se cadastrar.")