# src/admin_acoes.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from src.sheets import listar_membros, atualizar_membro, buscar_membro
from src.permissoes import get_nivel
import logging
import traceback

logger = logging.getLogger(__name__)

# Estados da conversação
SELECIONAR_MEMBRO, SELECIONAR_CAMPO, NOVO_VALOR = range(3)

# Mapeamento de campos editáveis (admin/secretário podem editar tudo exceto Telegram ID)
CAMPOS_EDITAVEIS = {
    "nome": {"nome": "Nome", "chave": "Nome", "nivel_minimo": "2"},
    "loja": {"nome": "Loja", "chave": "Loja", "nivel_minimo": "2"},
    "grau": {"nome": "Grau", "chave": "Grau", "nivel_minimo": "2"},
    "oriente": {"nome": "Oriente", "chave": "Oriente", "nivel_minimo": "2"},
    "potencia": {"nome": "Potência", "chave": "Potência", "nivel_minimo": "2"},
    "data_nasc": {"nome": "Data de nascimento", "chave": "Data de nascimento", "nivel_minimo": "2"},
    "numero_loja": {"nome": "Número da loja", "chave": "Número da loja", "nivel_minimo": "2"},
    "cargo": {"nome": "Cargo", "chave": "Cargo", "nivel_minimo": "2"},
    "nivel": {"nome": "Nível (1,2,3)", "chave": "Nivel", "nivel_minimo": "3"},  # Apenas admin pode editar nível
}

# --- Funções existentes (promover/rebaixar) ---
async def promover_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia promoção de membro comum para secretário."""
    query = update.callback_query
    await query.answer()

    if get_nivel(update.effective_user.id) != "3":
        await query.edit_message_text("Apenas administradores podem promover membros.")
        return ConversationHandler.END

    membros = listar_membros()
    if not membros:
        await query.edit_message_text("Nenhum membro cadastrado.")
        return ConversationHandler.END

    botoes = []
    for membro in membros:
        if membro.get("Nivel") == "1":
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
    return 1  # SELECIONAR_MEMBRO

async def selecionar_membro_promover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seleciona membro para promoção."""
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
    return 2  # CONFIRMAR_PROMOCAO

async def confirmar_promover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma promoção."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_promocao":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    telegram_id = context.user_data.get("promover_telegram_id")
    if not telegram_id:
        await query.edit_message_text("Erro: dados não encontrados.")
        return ConversationHandler.END

    from src.sheets import atualizar_nivel
    if atualizar_nivel(int(telegram_id), "2"):
        await query.edit_message_text("✅ Membro promovido a secretário com sucesso!")
    else:
        await query.edit_message_text("❌ Erro ao promover membro.")

    return ConversationHandler.END

async def rebaixar_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia rebaixamento de secretário para comum."""
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
        if membro.get("Nivel") == "2":
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
    return 1  # SELECIONAR_MEMBRO

async def selecionar_membro_rebaixar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seleciona membro para rebaixamento."""
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
    return 2  # CONFIRMAR_REBAIXAMENTO

async def confirmar_rebaixar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma rebaixamento."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancelar_rebaixamento":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    telegram_id = context.user_data.get("rebaixar_telegram_id")
    if not telegram_id:
        await query.edit_message_text("Erro: dados não encontrados.")
        return ConversationHandler.END

    from src.sheets import atualizar_nivel
    if atualizar_nivel(int(telegram_id), "1"):
        await query.edit_message_text("✅ Secretário rebaixado a comum com sucesso!")
    else:
        await query.edit_message_text("❌ Erro ao rebaixar membro.")

    return ConversationHandler.END

async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela operação."""
    await update.message.reply_text("Operação cancelada.")
    return ConversationHandler.END

# --- NOVA FUNÇÃO: Editar membro (admin e secretário) ---
async def editar_membro_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de edição de um membro (admin ou secretário)."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    # Verifica permissão (admin ou secretário)
    if nivel not in ["2", "3"]:
        await query.edit_message_text("⛔ Você não tem permissão para editar membros.")
        return ConversationHandler.END

    # Lista todos os membros (exceto o próprio se for secretário?)
    # Regra: secretário pode editar membros comuns (nível 1), admin pode editar todos
    membros = listar_membros()
    if not membros:
        await query.edit_message_text("Nenhum membro cadastrado.")
        return ConversationHandler.END

    botoes = []
    for membro in membros:
        membro_id = membro.get("Telegram ID")
        membro_nivel = membro.get("Nivel", "1")
        nome = membro.get("Nome", "Sem nome")
        
        # Secretário só pode editar membros comuns (nível 1)
        if nivel == "2" and membro_nivel != "1":
            continue
            
        # Não permitir que secretário edite admin ou outros secretários
        if nivel == "2" and membro_nivel in ["2", "3"]:
            continue
            
        botoes.append([InlineKeyboardButton(
            f"{nome} (Nível {membro_nivel})",
            callback_data=f"editar_membro_selecionar|{membro_id}"
        )])

    if not botoes:
        await query.edit_message_text(
            "Nenhum membro disponível para edição." if nivel == "2" else "Nenhum membro cadastrado.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar", callback_data="area_admin" if nivel == "3" else "area_secretario")
            ]])
        )
        return ConversationHandler.END

    botoes.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="cancelar_edicao")])
    teclado = InlineKeyboardMarkup(botoes)

    await query.edit_message_text(
        "Selecione o membro que deseja editar:",
        reply_markup=teclado
    )
    return SELECIONAR_MEMBRO

async def selecionar_membro_para_editar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usuário selecionou um membro para editar."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancelar_edicao":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    telegram_id = data.split("|")[1]
    membro = buscar_membro(int(telegram_id))
    
    if not membro:
        await query.edit_message_text("Membro não encontrado.")
        return ConversationHandler.END

    context.user_data["editando_membro_id"] = telegram_id
    context.user_data["editando_membro_dados"] = membro

    nivel_usuario = get_nivel(update.effective_user.id)
    
    # Cria botões para campos editáveis
    botoes = []
    for campo_id, campo_info in CAMPOS_EDITAVEIS.items():
        # Verifica se o usuário tem permissão para editar este campo
        if int(nivel_usuario) < int(campo_info["nivel_minimo"]):
            continue
            
        valor_atual = membro.get(campo_info["chave"], "Não informado")
        botoes.append([InlineKeyboardButton(
            f"✏️ {campo_info['nome']}: {str(valor_atual)[:30]}",
            callback_data=f"editar_campo_membro|{campo_id}"
        )])

    botoes.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="cancelar_edicao")])
    teclado = InlineKeyboardMarkup(botoes)

    await query.edit_message_text(
        f"Editando *{membro.get('Nome')}*\n\nSelecione o campo que deseja alterar:",
        parse_mode="Markdown",
        reply_markup=teclado
    )
    return SELECIONAR_CAMPO

async def selecionar_campo_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usuário selecionou um campo para editar."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancelar_edicao":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    campo_id = data.split("|")[1]
    campo_info = CAMPOS_EDITAVEIS.get(campo_id)

    if not campo_info:
        await query.edit_message_text("Campo inválido.")
        return ConversationHandler.END

    context.user_data["editando_campo"] = campo_id
    membro = context.user_data.get("editando_membro_dados", {})
    valor_atual = membro.get(campo_info["chave"], "Não informado")

    await query.edit_message_text(
        f"✏️ *Editando {campo_info['nome']}*\n\n"
        f"Valor atual: {valor_atual}\n\n"
        f"Digite o novo valor (ou /cancelar para desistir):",
        parse_mode="Markdown"
    )
    return NOVO_VALOR

async def receber_novo_valor_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o novo valor e atualiza o membro."""
    novo_valor = update.message.text.strip()
    campo_id = context.user_data.get("editando_campo")
    campo_info = CAMPOS_EDITAVEIS.get(campo_id)
    telegram_id = context.user_data.get("editando_membro_id")

    if not campo_info or not telegram_id:
        await update.message.reply_text("Erro: dados não encontrados. Tente novamente.")
        return ConversationHandler.END

    # Atualiza na planilha
    sucesso = atualizar_membro(int(telegram_id), campo_info["chave"], novo_valor)

    if sucesso:
        await update.message.reply_text(
            f"✅ {campo_info['nome']} atualizado com sucesso para: {novo_valor}\n\n"
            f"Use /start para voltar ao menu principal."
        )
    else:
        await update.message.reply_text(
            "❌ Erro ao atualizar o campo. Tente novamente mais tarde."
        )

    # Limpa dados da sessão
    context.user_data.pop("editando_membro_id", None)
    context.user_data.pop("editando_membro_dados", None)
    context.user_data.pop("editando_campo", None)

    return ConversationHandler.END

async def cancelar_edicao_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o processo de edição."""
    await update.message.reply_text("Edição cancelada.")
    context.user_data.pop("editando_membro_id", None)
    context.user_data.pop("editando_membro_dados", None)
    context.user_data.pop("editando_campo", None)
    return ConversationHandler.END

# Handlers de conversação
promover_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(promover_inicio, pattern="^admin_promover$")],
    states={
        1: [CallbackQueryHandler(selecionar_membro_promover, pattern="^(promover_|cancelar_promocao)")],
        2: [CallbackQueryHandler(confirmar_promover, pattern="^(confirmar_promover|cancelar_promocao)")],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
)

rebaixar_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(rebaixar_inicio, pattern="^admin_rebaixar$")],
    states={
        1: [CallbackQueryHandler(selecionar_membro_rebaixar, pattern="^(rebaixar_|cancelar_rebaixamento)")],
        2: [CallbackQueryHandler(confirmar_rebaixar, pattern="^(confirmar_rebaixar|cancelar_rebaixamento)")],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
)

# NOVO: Handler para editar membro
editar_membro_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(editar_membro_inicio, pattern="^admin_editar_membro$")],
    states={
        SELECIONAR_MEMBRO: [CallbackQueryHandler(selecionar_membro_para_editar, pattern="^(editar_membro_selecionar|cancelar_edicao)")],
        SELECIONAR_CAMPO: [CallbackQueryHandler(selecionar_campo_membro, pattern="^(editar_campo_membro|cancelar_edicao)")],
        NOVO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor_membro)],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_edicao_membro)],
)