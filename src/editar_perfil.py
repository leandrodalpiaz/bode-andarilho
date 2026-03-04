# src/editar_perfil.py
from __future__ import annotations

import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CommandHandler,
)

from src.sheets import buscar_membro, atualizar_membro
from src.permissoes import get_nivel

logger = logging.getLogger(__name__)

# Estados da conversação
SELECIONAR_CAMPO, NOVO_VALOR = range(2)

# Mapeamento de campos que o próprio usuário pode editar
CAMPOS_EDITAVEIS_PERFIL = {
    "nome": {"nome": "Nome completo", "chave": "Nome"},
    "data_nasc": {"nome": "Data de nascimento (DD/MM/AAAA)", "chave": "Data de nascimento"},
    "grau": {"nome": "Grau", "chave": "Grau"},
    "loja": {"nome": "Nome da loja", "chave": "Loja"},
    "numero_loja": {"nome": "Número da loja", "chave": "Número da loja"},
    "oriente": {"nome": "Oriente", "chave": "Oriente"},
    "potencia": {"nome": "Potência", "chave": "Potência"},
    "veneravel_mestre": {"nome": "Venerável Mestre (Sim/Não)", "chave": "Venerável Mestre"},
}


async def _safe_edit(query, text: str, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


async def editar_perfil_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de edição do próprio perfil."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    user_id = update.effective_user.id
    membro = buscar_membro(user_id)
    if not membro:
        await _safe_edit(query, "Você ainda não possui cadastro. Use /start para iniciar.")
        return ConversationHandler.END

    # Guarda os dados do membro no context
    context.user_data["perfil_dados"] = membro

    # Cria botões para os campos editáveis
    botoes = []
    for campo_id, campo_info in CAMPOS_EDITAVEIS_PERFIL.items():
        valor_atual = membro.get(campo_info["chave"], "")
        if valor_atual is None:
            valor_atual = ""
        botoes.append([
            InlineKeyboardButton(
                f"✏️ {campo_info['nome']}: {str(valor_atual)[:30]}",
                callback_data=f"editar_campo_perfil|{campo_id}"
            )
        ])

    botoes.append([InlineKeyboardButton("⬅️ Cancelar", callback_data="menu_principal")])
    teclado = InlineKeyboardMarkup(botoes)

    await _safe_edit(
        query,
        f"*Editando seu perfil*\n\n"
        f"Selecione o campo que deseja alterar:",
        parse_mode="Markdown",
        reply_markup=teclado,
    )
    return SELECIONAR_CAMPO


async def selecionar_campo_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usuário selecionou um campo para editar."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    data = query.data
    if not data.startswith("editar_campo_perfil|"):
        return ConversationHandler.END

    campo_id = data.split("|")[1]
    campo_info = CAMPOS_EDITAVEIS_PERFIL.get(campo_id)
    if not campo_info:
        await _safe_edit(query, "Campo inválido.")
        return ConversationHandler.END

    context.user_data["editando_campo_perfil"] = campo_id
    membro = context.user_data.get("perfil_dados", {})
    valor_atual = membro.get(campo_info["chave"], "")

    await _safe_edit(
        query,
        f"✏️ *Editando {campo_info['nome']}*\n\n"
        f"Valor atual: {valor_atual}\n\n"
        f"Digite o novo valor (ou /cancelar para desistir):",
        parse_mode="Markdown",
    )
    return NOVO_VALOR


async def receber_novo_valor_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o novo valor e atualiza o perfil."""
    novo_valor = update.message.text.strip()
    campo_id = context.user_data.get("editando_campo_perfil")
    if not campo_id:
        await update.message.reply_text("Erro: dados não encontrados. Tente novamente.")
        return ConversationHandler.END

    campo_info = CAMPOS_EDITAVEIS_PERFIL.get(campo_id)
    membro = context.user_data.get("perfil_dados")
    if not campo_info or not membro:
        await update.message.reply_text("Erro: dados do perfil não encontrados.")
        return ConversationHandler.END

    # Atualiza o dicionário do membro
    membro[campo_info["chave"]] = novo_valor

    # Salva na planilha (atualiza apenas o campo alterado)
    # A função atualizar_membro aceita um dicionário com as alterações
    user_id = update.effective_user.id
    sucesso = atualizar_membro(user_id, {campo_info["chave"]: novo_valor}, preservar_nivel=True)

    if sucesso:
        await update.message.reply_text(
            f"✅ {campo_info['nome']} atualizado com sucesso para:\n{novo_valor}\n\n"
            f"Use /start para voltar ao menu principal."
        )
    else:
        await update.message.reply_text("❌ Erro ao atualizar o campo. Tente novamente mais tarde.")

    # Limpa dados da sessão
    context.user_data.pop("editando_campo_perfil", None)
    context.user_data.pop("perfil_dados", None)
    return ConversationHandler.END


async def cancelar_edicao_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o processo de edição."""
    await update.message.reply_text("Edição cancelada.")
    context.user_data.pop("editando_campo_perfil", None)
    context.user_data.pop("perfil_dados", None)
    return ConversationHandler.END


# ConversationHandler para editar perfil
editar_perfil_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(editar_perfil_inicio, pattern="^editar_perfil$")],
    states={
        SELECIONAR_CAMPO: [CallbackQueryHandler(selecionar_campo_perfil, pattern="^editar_campo_perfil\|")],
        NOVO_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor_perfil)],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_edicao_perfil),
        CallbackQueryHandler(cancelar_edicao_perfil, pattern="^cancelar$"),
    ],
)