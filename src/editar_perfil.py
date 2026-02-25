# src/editar_perfil.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from src.sheets import buscar_membro, atualizar_membro

# Estados da conversação
SELECIONAR_CAMPO, NOVO_VALOR = range(2)

# Mapeamento de campos para nomes amigáveis e chaves na planilha
CAMPOS = {
    "nome": {"nome": "Nome", "chave": "Nome"},
    "loja": {"nome": "Loja", "chave": "Loja"},
    "grau": {"nome": "Grau", "chave": "Grau"},
    "oriente": {"nome": "Oriente", "chave": "Oriente"},
    "potencia": {"nome": "Potência", "chave": "Potência"},
    "telefone": {"nome": "Telefone", "chave": "Telefone"},
}

async def editar_perfil_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de edição de perfil."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    if not membro:
        await query.edit_message_text("Seu cadastro não foi encontrado. Envie /start para se cadastrar.")
        return ConversationHandler.END

    # Armazena os dados atuais do membro
    context.user_data["membro_atual"] = membro

    # Cria botões para cada campo editável
    botoes = []
    for campo_id, campo_info in CAMPOS.items():
        valor_atual = membro.get(campo_info["chave"], "Não informado")
        botoes.append([InlineKeyboardButton(
            f"✏️ {campo_info['nome']}: {valor_atual}",
            callback_data=f"editar_campo|{campo_id}"
        )])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="meu_cadastro")])

    teclado = InlineKeyboardMarkup(botoes)

    await query.edit_message_text(
        "👤 *Editar Perfil*\n\n"
        "Selecione o campo que deseja atualizar:",
        parse_mode="Markdown",
        reply_markup=teclado
    )
    return SELECIONAR_CAMPO

async def selecionar_campo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usuário selecionou um campo para editar."""
    query = update.callback_query
    await query.answer()

    campo_id = query.data.split("|")[1]
    campo_info = CAMPOS.get(campo_id)

    if not campo_info:
        await query.edit_message_text("Campo inválido.")
        return ConversationHandler.END

    context.user_data["campo_editando"] = campo_id
    membro = context.user_data.get("membro_atual", {})
    valor_atual = membro.get(campo_info["chave"], "Não informado")

    await query.edit_message_text(
        f"✏️ *Editando {campo_info['nome']}*\n\n"
        f"Valor atual: {valor_atual}\n\n"
        f"Digite o novo valor para {campo_info['nome']} (ou /cancelar para desistir):",
        parse_mode="Markdown"
    )
    return NOVO_VALOR

async def receber_novo_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o novo valor digitado pelo usuário."""
    novo_valor = update.message.text.strip()
    campo_id = context.user_data.get("campo_editando")
    campo_info = CAMPOS.get(campo_id)

    if not campo_info:
        await update.message.reply_text("Erro: campo não identificado. Tente novamente.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    membro = context.user_data.get("membro_atual", {})

    # Atualiza o campo na planilha
    sucesso = atualizar_membro(user_id, campo_info["chave"], novo_valor)

    if sucesso:
        await update.message.reply_text(
            f"✅ {campo_info['nome']} atualizado com sucesso para: {novo_valor}\n\n"
            "Use /start para voltar ao menu principal."
        )
    else:
        await update.message.reply_text(
            "❌ Erro ao atualizar o campo. Tente novamente mais tarde."
        )

    # Limpa dados da sessão
    context.user_data.pop("campo_editando", None)
    context.user_data.pop("membro_atual", None)

    return ConversationHandler.END

async def cancelar_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o processo de edição."""
    await update.message.reply_text("Edição cancelada. Use /start para voltar ao menu principal.")
    return ConversationHandler.END

# ConversationHandler para edição de perfil
editar_perfil_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(editar_perfil_start, pattern="^editar_perfil$")],
    states={
        SELECIONAR_CAMPO: [CallbackQueryHandler(selecionar_campo, pattern="^editar_campo\\|")],
        NOVO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor)],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_edicao)],
)