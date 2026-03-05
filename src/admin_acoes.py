# src/admin_acoes.py
from __future__ import annotations

import logging
import traceback
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from src.sheets import listar_membros, atualizar_membro, buscar_membro, atualizar_nivel_membro, get_notificacao_status, set_notificacao_status
from src.permissoes import get_nivel

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
    "veneravel_mestre": {"nome": "Venerável Mestre (Sim/Não)", "chave": "Venerável Mestre", "nivel_minimo": "2"},
    "nivel": {"nome": "Nível (1,2,3)", "chave": "Nivel", "nivel_minimo": "3"},  # Apenas admin pode editar nível
}


async def _safe_edit(query, text: str, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


# =========================
# Gerenciamento de notificações para secretários (persistente)
# =========================
async def menu_notificacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu para o secretário gerenciar notificações."""
    query = update.callback_query
    if not query:
        return
    await query.answer("🔔 Carregando configurações...")

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _safe_edit(query, "⛔ Apenas secretários e administradores podem acessar esta função.")
        return

    # Busca status atual da planilha
    ativo = get_notificacao_status(user_id)
    status_texto = "✅ Ativadas" if ativo else "🔕 Desativadas"

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Ativar notificações", callback_data="notificacoes_ativar")],
        [InlineKeyboardButton("🔕 Desativar notificações", callback_data="notificacoes_desativar")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="area_secretario" if nivel == "2" else "area_admin")],
    ])

    await _safe_edit(
        query,
        f"🔔 *Configurações de Notificações*\n\n"
        f"Status atual: {status_texto}\n\n"
        f"Quando ativadas, você receberá uma mensagem no privado "
        f"cada vez que alguém confirmar presença em um evento que você criou.\n\n"
        f"*Nota:* Esta configuração é permanente e ficará salva na planilha.",
        parse_mode="Markdown",
        reply_markup=teclado,
    )


async def notificacoes_ativar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ativa as notificações para o secretário (salva na planilha)."""
    query = update.callback_query
    if not query:
        return
    await query.answer("✅ Ativando notificações...")

    user_id = update.effective_user.id
    
    if set_notificacao_status(user_id, True):
        await _safe_edit(
            query,
            "✅ *Notificações ativadas com sucesso!*\n\n"
            "Agora você receberá alertas de novas confirmações.\n"
            "Esta configuração está salva permanentemente.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar", callback_data="menu_notificacoes")
            ]]),
        )
    else:
        await _safe_edit(
            query,
            "❌ *Erro ao ativar notificações.*\n\n"
            "Tente novamente mais tarde ou contate o administrador.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar", callback_data="menu_notificacoes")
            ]]),
        )


async def notificacoes_desativar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Desativa as notificações para o secretário (salva na planilha)."""
    query = update.callback_query
    if not query:
        return
    await query.answer("🔕 Desativando notificações...")

    user_id = update.effective_user.id
    
    if set_notificacao_status(user_id, False):
        await _safe_edit(
            query,
            "🔕 *Notificações desativadas com sucesso!*\n\n"
            "Você não receberá mais alertas de novas confirmações.\n"
            "Esta configuração está salva permanentemente.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar", callback_data="menu_notificacoes")
            ]]),
        )
    else:
        await _safe_edit(
            query,
            "❌ *Erro ao desativar notificações.*\n\n"
            "Tente novamente mais tarde ou contate o administrador.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar", callback_data="menu_notificacoes")
            ]]),
        )


# =========================
# Promover membro (comum -> secretário)
# =========================
async def promover_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia promoção de membro comum para secretário."""
    query = update.callback_query
    await query.answer("🟢 Carregando lista de membros...")

    if get_nivel(update.effective_user.id) != "3":
        await query.edit_message_text("Apenas administradores podem promover membros.")
        return ConversationHandler.END

    membros = listar_membros()
    if not membros:
        await query.edit_message_text("Nenhum membro cadastrado.")
        return ConversationHandler.END

    botoes = []
    for membro in membros:
        nivel = str(membro.get("Nivel", "1")).strip()
        if nivel == "1":  # Apenas membros comuns
            nome = membro.get("Nome", "Sem nome")
            telegram_id = membro.get("Telegram ID")
            # Converte para inteiro para garantir formato
            try:
                tid = int(float(telegram_id))
                botoes.append([InlineKeyboardButton(nome, callback_data=f"promover_{tid}")])
            except:
                continue

    if not botoes:
        await query.edit_message_text("Não há membros comuns para promover.")
        return ConversationHandler.END

    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_promocao")])
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

    try:
        telegram_id = int(data.split("_")[1])
    except:
        await query.edit_message_text("Erro ao processar seleção.")
        return ConversationHandler.END

    context.user_data["promover_telegram_id"] = telegram_id

    membro = buscar_membro(telegram_id)
    if not membro:
        await query.edit_message_text("Membro não encontrado.")
        return ConversationHandler.END

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, promover", callback_data="confirmar_promover")],
        [InlineKeyboardButton("❌ Não, cancelar", callback_data="cancelar_promocao")]
    ])

    await query.edit_message_text(
        f"Confirmar promoção de *{membro.get('Nome')}* para secretário?",
        parse_mode="Markdown",
        reply_markup=teclado
    )
    return 2  # CONFIRMAR_PROMOCAO


async def confirmar_promover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma promoção e atualiza o cargo para 'Secretário'."""
    query = update.callback_query
    await query.answer("🟢 Promovendo membro...")

    if query.data == "cancelar_promocao":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    telegram_id = context.user_data.get("promover_telegram_id")
    if not telegram_id:
        await query.edit_message_text("Erro: dados não encontrados.")
        return ConversationHandler.END

    # Atualiza nível para secretário (2)
    if atualizar_nivel_membro(telegram_id, "2"):
        # Atualiza o cargo para "Secretário"
        atualizar_membro(telegram_id, {"Cargo": "Secretário"}, preservar_nivel=True)
        await query.edit_message_text("✅ Membro promovido a secretário com sucesso!")
    else:
        await query.edit_message_text("❌ Erro ao promover membro.")

    # Limpa dados
    context.user_data.pop("promover_telegram_id", None)
    return ConversationHandler.END


# =========================
# Rebaixar membro (secretário -> comum)
# =========================
async def rebaixar_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia rebaixamento de secretário para comum."""
    query = update.callback_query
    await query.answer("🔻 Carregando lista de secretários...")

    if get_nivel(update.effective_user.id) != "3":
        await query.edit_message_text("Apenas administradores podem rebaixar membros.")
        return ConversationHandler.END

    membros = listar_membros()
    if not membros:
        await query.edit_message_text("Nenhum membro cadastrado.")
        return ConversationHandler.END

    botoes = []
    for membro in membros:
        nivel = str(membro.get("Nivel", "1")).strip()
        if nivel == "2":  # Apenas secretários
            nome = membro.get("Nome", "Sem nome")
            telegram_id = membro.get("Telegram ID")
            try:
                tid = int(float(telegram_id))
                botoes.append([InlineKeyboardButton(nome, callback_data=f"rebaixar_{tid}")])
            except:
                continue

    if not botoes:
        await query.edit_message_text("Não há secretários para rebaixar.")
        return ConversationHandler.END

    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_rebaixamento")])
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

    try:
        telegram_id = int(data.split("_")[1])
    except:
        await query.edit_message_text("Erro ao processar seleção.")
        return ConversationHandler.END

    context.user_data["rebaixar_telegram_id"] = telegram_id

    membro = buscar_membro(telegram_id)
    if not membro:
        await query.edit_message_text("Membro não encontrado.")
        return ConversationHandler.END

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, rebaixar", callback_data="confirmar_rebaixar")],
        [InlineKeyboardButton("❌ Não, cancelar", callback_data="cancelar_rebaixamento")]
    ])

    await query.edit_message_text(
        f"Confirmar rebaixamento de *{membro.get('Nome')}* para comum?",
        parse_mode="Markdown",
        reply_markup=teclado
    )
    return 2  # CONFIRMAR_REBAIXAMENTO


async def confirmar_rebaixar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma rebaixamento e limpa o cargo."""
    query = update.callback_query
    await query.answer("🔻 Rebaixando membro...")

    if query.data == "cancelar_rebaixamento":
        await query.edit_message_text("Operação cancelada.")
        return ConversationHandler.END

    telegram_id = context.user_data.get("rebaixar_telegram_id")
    if not telegram_id:
        await query.edit_message_text("Erro: dados não encontrados.")
        return ConversationHandler.END

    # Rebaixa para comum (nível 1)
    if atualizar_nivel_membro(telegram_id, "1"):
        # Limpa o cargo (volta a ser vazio)
        atualizar_membro(telegram_id, {"Cargo": ""}, preservar_nivel=True)
        await query.edit_message_text("✅ Secretário rebaixado a comum com sucesso!")
    else:
        await query.edit_message_text("❌ Erro ao rebaixar membro.")

    # Limpa dados
    context.user_data.pop("rebaixar_telegram_id", None)
    return ConversationHandler.END


# =========================
# Ver todos os membros
# =========================
async def ver_todos_membros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todos os membros para o administrador."""
    query = update.callback_query
    if not query:
        return
    await query.answer("👥 Buscando lista de membros...")

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    if nivel != "3":
        await _safe_edit(query, "⛔ Apenas administradores podem ver todos os membros.")
        return

    membros = listar_membros()
    if not membros:
        await _safe_edit(query, "Nenhum membro cadastrado.")
        return

    # Divide em lotes para não exceder limite de mensagem
    linhas = []
    for membro in membros[:50]:  # limite de 50 membros por vez
        nome = membro.get("Nome", "Sem nome")
        nivel = membro.get("Nivel", "1")
        cargo = membro.get("Cargo", "")
        loja = membro.get("Loja", "")
        nivel_texto = {"1": "👤", "2": "🔰", "3": "⚜️"}.get(str(nivel), "👤")
        
        if cargo:
            linha = f"{nivel_texto} *{nome}* - {cargo} - {loja} (Nível {nivel})"
        else:
            linha = f"{nivel_texto} *{nome}* - {loja} (Nível {nivel})"
        
        linhas.append(linha)

    if not linhas:
        await _safe_edit(query, "Nenhum membro listado.")
        return

    texto = "*Membros cadastrados:*\n\n" + "\n".join(linhas)

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Voltar", callback_data="area_admin")]
    ])

    await _safe_edit(query, texto, parse_mode="Markdown", reply_markup=teclado)


# =========================
# Editar membro (admin e secretário)
# =========================
async def editar_membro_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de edição de um membro (admin ou secretário)."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer("✏️ Carregando lista de membros...")

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)

    # Verifica permissão (admin ou secretário)
    if nivel not in ["2", "3"]:
        await query.edit_message_text("⛔ Você não tem permissão para editar membros.")
        return ConversationHandler.END

    # Lista todos os membros
    membros = listar_membros()
    if not membros:
        await query.edit_message_text("Nenhum membro cadastrado.")
        return ConversationHandler.END

    botoes = []
    for membro in membros:
        membro_id = membro.get("Telegram ID")
        membro_nivel = str(membro.get("Nivel", "1")).strip()
        nome = membro.get("Nome", "Sem nome")
        cargo = membro.get("Cargo", "")

        # Converte ID para inteiro
        try:
            tid = int(float(membro_id))
        except:
            continue

        # Secretário só pode editar membros comuns (nível 1)
        if nivel == "2" and membro_nivel != "1":
            continue

        # Não permitir que secretário edite admin ou outros secretários
        if nivel == "2" and membro_nivel in ["2", "3"]:
            continue

        texto_botao = f"{nome} (Nível {membro_nivel})"
        if cargo:
            texto_botao = f"{nome} - {cargo} (Nível {membro_nivel})"

        botoes.append([InlineKeyboardButton(
            texto_botao,
            callback_data=f"editar_membro_selecionar|{tid}"
        )])

    if not botoes:
        await query.edit_message_text(
            "Nenhum membro disponível para edição." if nivel == "2" else "Nenhum membro cadastrado.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar", callback_data="area_admin" if nivel == "3" else "area_secretario")
            ]])
        )
        return ConversationHandler.END

    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_edicao")])
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

    try:
        telegram_id = int(data.split("|")[1])
    except:
        await query.edit_message_text("Erro ao processar seleção.")
        return ConversationHandler.END

    membro = buscar_membro(telegram_id)

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

        valor_atual = membro.get(campo_info["chave"], "")
        if valor_atual is None:
            valor_atual = ""
        botoes.append([InlineKeyboardButton(
            f"✏️ {campo_info['nome']}: {str(valor_atual)[:30]}",
            callback_data=f"editar_campo_membro|{campo_id}"
        )])

    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_edicao")])
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
    valor_atual = membro.get(campo_info["chave"], "")

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

    # Validações específicas
    if campo_id == "nivel":
        if novo_valor not in ("1", "2", "3"):
            await update.message.reply_text("❌ Nível inválido. Use 1, 2 ou 3.")
            return NOVO_VALOR

    # Atualiza na planilha (apenas o campo alterado)
    sucesso = atualizar_membro(telegram_id, {campo_info["chave"]: novo_valor}, preservar_nivel=(campo_id != "nivel"))

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


async def cancelar_operacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela operação (fallback)."""
    if update.message:
        await update.message.reply_text("Operação cancelada.")
    elif update.callback_query:
        await update.callback_query.edit_message_text("Operação cancelada.")
    return ConversationHandler.END


# =========================
# Handlers de conversação
# =========================
promover_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(promover_inicio, pattern="^admin_promover$")],
    states={
        1: [CallbackQueryHandler(selecionar_membro_promover, pattern="^(promover_|cancelar_promocao)")],
        2: [CallbackQueryHandler(confirmar_promover, pattern="^(confirmar_promover|cancelar_promocao)")],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    name="promover_handler",
    persistent=False,
)

rebaixar_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(rebaixar_inicio, pattern="^admin_rebaixar$")],
    states={
        1: [CallbackQueryHandler(selecionar_membro_rebaixar, pattern="^(rebaixar_|cancelar_rebaixamento)")],
        2: [CallbackQueryHandler(confirmar_rebaixar, pattern="^(confirmar_rebaixar|cancelar_rebaixamento)")],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_operacao)],
    name="rebaixar_handler",
    persistent=False,
)

editar_membro_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(editar_membro_inicio, pattern="^admin_editar_membro$")],
    states={
        SELECIONAR_MEMBRO: [CallbackQueryHandler(selecionar_membro_para_editar, pattern="^(editar_membro_selecionar|cancelar_edicao)")],
        SELECIONAR_CAMPO: [CallbackQueryHandler(selecionar_campo_membro, pattern="^(editar_campo_membro|cancelar_edicao)")],
        NOVO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor_membro)],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_edicao_membro),
        CallbackQueryHandler(cancelar_edicao_membro, pattern="^cancelar$"),
    ],
    name="editar_membro_handler",
    persistent=False,
)