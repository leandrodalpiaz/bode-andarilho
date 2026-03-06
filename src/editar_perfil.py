# src/editar_perfil.py
# ============================================
# BODE ANDARILHO - EDIÇÃO DO PRÓPRIO PERFIL
# ============================================
# 
# Este módulo permite que o membro edite seu próprio cadastro.
# Diferente da edição feita por admin/secretário, aqui o usuário
# só pode alterar seus próprios dados e não pode modificar o nível.
# 
# Funcionalidades:
# - Seleção de campo para editar (nome, data nasc, grau, loja, etc.)
# - Validação dos novos valores
# - Atualização na planilha
# 
# Utiliza um ConversationHandler para gerenciar o fluxo de edição.
# 
# ============================================

from __future__ import annotations

import logging
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

from src.sheets import buscar_membro, atualizar_membro
from src.permissoes import get_nivel

from src.bot import (
    navegar_para,
    voltar_ao_menu_principal,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

logger = logging.getLogger(__name__)

# ============================================
# CONSTANTES E CONFIGURAÇÕES
# ============================================

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


# ============================================
# FUNÇÕES AUXILIARES
# ============================================

async def _safe_edit(query, text: str, **kwargs):
    """Edita mensagem ignorando erro 'Message not modified'."""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


# ============================================
# INÍCIO DA EDIÇÃO
# ============================================

async def editar_perfil_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Inicia o processo de edição do próprio perfil.
    
    Fluxo:
    1. Verifica se usuário tem cadastro
    2. Exibe lista de campos editáveis com valores atuais
    3. Usuário seleciona qual campo deseja alterar
    """
    query = update.callback_query
    user_id = update.effective_user.id
    
    membro = buscar_membro(user_id)
    if not membro:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Você ainda não possui cadastro. Use /start para iniciar."
        )
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

    botoes.append([InlineKeyboardButton("🔙 Cancelar", callback_data="menu_principal")])
    teclado = InlineKeyboardMarkup(botoes)

    await navegar_para(
        update, context,
        "Editar Perfil",
        f"*Editando seu perfil*\n\nSelecione o campo que deseja alterar:",
        teclado
    )
    return SELECIONAR_CAMPO


# ============================================
# SELEÇÃO DE CAMPO
# ============================================

async def selecionar_campo_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usuário selecionou um campo para editar.
    
    Fluxo:
    1. Identifica o campo escolhido
    2. Mostra valor atual e solicita novo valor
    3. Aguarda entrada do usuário
    """
    query = update.callback_query
    data = query.data
    
    if data == "cancelar":
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Edição cancelada."
        )
        return ConversationHandler.END

    campo_id = data.split("|")[1]
    campo_info = CAMPOS_EDITAVEIS_PERFIL.get(campo_id)

    if not campo_info:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Campo inválido."
        )
        return ConversationHandler.END

    context.user_data["editando_campo_perfil"] = campo_id
    membro = context.user_data.get("perfil_dados", {})
    valor_atual = membro.get(campo_info["chave"], "")

    await navegar_para(
        update, context,
        f"Editar Perfil > {campo_info['nome']}",
        f"✏️ *Editando {campo_info['nome']}*\n\n"
        f"Valor atual: {valor_atual}\n\n"
        f"Digite o novo valor (ou /cancelar para desistir):",
        None
    )
    return NOVO_VALOR


# ============================================
# RECEBIMENTO DO NOVO VALOR
# ============================================

async def receber_novo_valor_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Recebe o novo valor digitado pelo usuário e atualiza o perfil.
    
    Fluxo:
    1. Recebe o texto digitado
    2. Valida o campo (se necessário)
    3. Atualiza na planilha
    4. Confirma sucesso ou erro
    """
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

    # Validações específicas por campo
    if campo_id == "veneravel_mestre":
        if novo_valor.lower() not in ["sim", "não", "s", "n", "yes", "no"]:
            await update.message.reply_text(
                "❌ Valor inválido. Digite 'Sim' ou 'Não'."
            )
            return NOVO_VALOR

    # Atualiza o dicionário do membro
    membro[campo_info["chave"]] = novo_valor

    # Salva na planilha (atualiza apenas o campo alterado)
    user_id = update.effective_user.id
    sucesso = atualizar_membro(user_id, {campo_info["chave"]: novo_valor}, preservar_nivel=True)

    if sucesso:
        await update.message.reply_text(
            f"✅ {campo_info['nome']} atualizado com sucesso!\n\n"
            f"Use o menu acima para continuar."
        )
    else:
        await update.message.reply_text(
            "❌ Erro ao atualizar o campo. Tente novamente mais tarde."
        )

    # Limpa dados da sessão
    context.user_data.pop("editando_campo_perfil", None)
    context.user_data.pop("perfil_dados", None)

    return ConversationHandler.END


# ============================================
# CANCELAMENTO
# ============================================

async def cancelar_edicao_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Cancela o processo de edição.
    Pode ser chamado via comando /cancelar ou callback.
    """
    if update.message:
        await update.message.reply_text("Edição cancelada.")
    elif update.callback_query:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "Edição cancelada."
        )
    
    context.user_data.pop("editando_campo_perfil", None)
    context.user_data.pop("perfil_dados", None)
    return ConversationHandler.END


# ============================================
# CONVERSATION HANDLER
# ============================================

editar_perfil_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(editar_perfil_inicio, pattern="^editar_perfil$")],
    states={
        SELECIONAR_CAMPO: [
            CallbackQueryHandler(selecionar_campo_perfil, pattern=r"^editar_campo_perfil\|"),
            CallbackQueryHandler(cancelar_edicao_perfil, pattern="^cancelar$")
        ],
        NOVO_VALOR: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_valor_perfil)
        ],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_edicao_perfil),
        CallbackQueryHandler(cancelar_edicao_perfil, pattern="^cancelar$"),
    ],
)