# src/admin_acoes.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, CommandHandler
from src.sheets import listar_membros, atualizar_nivel, buscar_membro
from src.permissoes import get_nivel

# Estados da conversação
SELECIONAR_MEMBRO, CONFIRMAR_PROMOCAO, CONFIRMAR_REBAIXAMENTO = range(3)

# --- Promover a secretário ---
async def promover_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Verifica se é admin (nível 3)
    if get_nivel(update.effective_user.id) != "3":
        await query.edit_message_text("Apenas administradores podem promover membros.")
        return ConversationHandler.END

    membros = listar_membros()
    if not membros:
        await query.edit_message_text("Nenhum membro cadastrado.")
        return ConversationHandler.END

    # Cria botões com os nomes dos membros (apenas nível 1)
    botoes = []
    for membro in membros:
        if membro.get("Nivel") == "1":  # só mostra membros comuns
            nome = membro.get("Nome", "Sem nome")
            telegram_id = membro.get("Telegram ID")
            botoes.append([InlineKeyboardButton(nome, callback_data=f"promover_{telegram_id}")])

    if not botoes:
        await query.edit_message_text("Não há membros comuns para promover.")
        return ConversationHandler.END

    botoes.append([InlineKeyboardButton("Cancelar", callback_data="cancelar_promocao")])
    teclado = InlineKeyboardMarkup(botoes)

    await query.edit_message_text(
        "Selecione o membro que deseja promover a **secretário**:",
        parse_mode="Markdown",
        reply_markup=teclado
    )
    return SELECIONAR_MEMBRO

async def selecionar_membro_promover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancelar_promocao":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    telegram_id = data.split("_")[1]
    context.user_data["promover_telegram_id"] = telegram_id

    membro = buscar_membro(int(telegram_id))
    if not membro:
        await query.edit_message_text("Membro não encontrado.")
        return ConversationHandler.END

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Sim, promover", callback_data="confirmar_promover")],
        [InlineKeyboardButton("Não, cancelar", callback_data="cancelar_promocao")]
    ])

    await query.edit_message_text(
        f"Confirmar promoção de *{membro.get('Nome')}* para secretário?",
        parse_mode="Markdown",
        reply_markup=teclado
    )
    return CONFIRMAR_PROMOCAO

async def confirmar_promover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_promocao":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    telegram_id = context.user_data.get("promover_telegram_id")
    if not telegram_id:
        await query.edit_message_text("Erro: dados não encontrados.")
        return ConversationHandler.END

    if atualizar_nivel(int(telegram_id), "2"):
        await query.edit_message_text("✅ Membro promovido a secretário com sucesso!")
    else:
        await query.edit_message_text("❌ Erro ao promover membro.")

    return ConversationHandler.END

# --- Rebaixar de secretário ---
async def rebaixar_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if get_nivel(update.effective_user.id) != "3":
        await query.edit_message_text("Apenas administradores podem rebaixar membros.")
        return ConversationHandler.END

    membros = listar_membros()
    if not membros:
        await query.edit_message_text("Nenhum membro cadastrado.")
        return ConversationHandler.END

    botoes = []
    for membro in membros:
        if membro.get("Nivel") == "2":  # só mostra secretários
            nome = membro.get("Nome", "Sem nome")
            telegram_id = membro.get("Telegram ID")
            botoes.append([InlineKeyboardButton(nome, callback_data=f"rebaixar_{telegram_id}")])

    if not botoes:
        await query.edit_message_text("Não há secretários para rebaixar.")
        return ConversationHandler.END

    botoes.append([InlineKeyboardButton("Cancelar", callback_data="cancelar_rebaixamento")])
    teclado = InlineKeyboardMarkup(botoes)

    await query.edit_message_text(
        "Selecione o secretário que deseja rebaixar a **comum**:",
        parse_mode="Markdown",
        reply_markup=teclado
    )
    return SELECIONAR_MEMBRO

async def selecionar_membro_rebaixar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancelar_rebaixamento":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    telegram_id = data.split("_")[1]
    context.user_data["rebaixar_telegram_id"] = telegram_id

    membro = buscar_membro(int(telegram_id))
    if not membro:
        await query.edit_message_text("Membro não encontrado.")
        return ConversationHandler.END

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Sim, rebaixar", callback_data="confirmar_rebaixar")],
        [InlineKeyboardButton("Não, cancelar", callback_data="cancelar_rebaixamento")]
    ])

    await query.edit_message_text(
        f"Confirmar rebaixamento de *{membro.get('Nome')}* para comum?",
        parse_mode="Markdown",
        reply_markup=teclado
    )
    return CONFIRMAR_REBAIXAMENTO

async def confirmar_rebaixar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_rebaixamento":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    telegram_id = context.user_data.get("rebaixar_telegram_id")
    if not telegram_id:
        await query.edit_message_text("Erro: dados não encontrados.")
        return ConversationHandler.END

    if atualizar_nivel(int(telegram_id), "1"):
        await query.edit_message_text("✅ Secretário rebaixado a comum com sucesso!")
    else:
        await query.edit_message_text("❌ Erro ao rebaixar membro.")

    return ConversationHandler.END

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operação cancelada.")
    return ConversationHandler.END

# Handlers de conversação
promover_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(promover_inicio, pattern="^admin_promover$")],
    states={
        SELECIONAR_MEMBRO: [CallbackQueryHandler(selecionar_membro_promover, pattern="^(promover_|cancelar_promocao)")],
        CONFIRMAR_PROMOCAO: [CallbackQueryHandler(confirmar_promover, pattern="^(confirmar_promover|cancelar_promocao)")],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
)

rebaixar_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(rebaixar_inicio, pattern="^admin_rebaixar$")],
    states={
        SELECIONAR_MEMBRO: [CallbackQueryHandler(selecionar_membro_rebaixar, pattern="^(rebaixar_|cancelar_rebaixamento)")],
        CONFIRMAR_REBAIXAMENTO: [CallbackQueryHandler(confirmar_rebaixar, pattern="^(confirmar_rebaixar|cancelar_rebaixamento)")],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
)