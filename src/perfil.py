# src/perfil.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.sheets import buscar_membro

async def mostrar_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra o perfil do usuário. Se estiver em grupo, redireciona para privado."""
    query = update.callback_query
    await query.answer()

    # Se a interação veio de um grupo, redireciona para privado
    if update.effective_chat.type in ["group", "supergroup"]:
        await query.edit_message_text(
            "🔔 Seus dados pessoais só podem ser visualizados no meu chat privado.\n\n"
            "Por favor, clique no meu nome e envie /start no privado para acessar seu cadastro."
        )
        
        # Envia uma mensagem no privado para facilitar
        user_id = update.effective_user.id
        await context.bot.send_message(
            chat_id=user_id,
            text="👤 Para ver e editar seu cadastro, use o menu abaixo:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 Meu cadastro", callback_data="meu_cadastro")
            ]])
        )
        return

    # Se já está em privado, mostra o perfil
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
            f"Nível: {membro.get('Nivel', '1')}\n"
        )
        # Botão para editar
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Editar dados", callback_data="editar_perfil")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")]
        ])
        await query.edit_message_text(texto_perfil, parse_mode="Markdown", reply_markup=teclado)
    else:
        await query.edit_message_text("Seu cadastro não foi encontrado. Envie /start para se cadastrar.")