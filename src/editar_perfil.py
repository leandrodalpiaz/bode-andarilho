# ============================================
# BODE ANDARILHO - EDIÇÃO DE DADOS DO OBREIRO
# ============================================
# 
# Este módulo permite que o Irmão realize ajustes em seu
# próprio traçado (cadastro), garantindo a exatidão das
# informações para a recepção nas Lojas.
# 
# Funcionalidades:
# - Ajuste de dados (Nome, Grau, Loja, etc.)
# - Validação fraterna dos valores inseridos
# - Atualização segura e acobertada na base de dados
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
from src.bot import (
    navegar_para,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

logger = logging.getLogger(__name__)

# ============================================
# CONFIGURAÇÕES DE ESTADO
# ============================================

SELECIONAR_CAMPO, NOVO_VALOR = range(2)

# Mapeamento de colunas para termos maçônicos e amigáveis
CAMPOS_EDITAVEIS_PERFIL = {
    "nome": {"nome": "Nome Civil", "chave": "Nome"},
    "data_nasc": {"nome": "Data de Nascimento", "chave": "Data de nascimento"},
    "grau": {"nome": "Grau atual", "chave": "Grau"},
    "loja": {"nome": "Augusta e Respeitável Loja", "chave": "Loja"},
    "numero_loja": {"nome": "Número da Loja", "chave": "Número da loja"},
    "oriente": {"nome": "Oriente", "chave": "Oriente"},
    "potencia": {"nome": "Potência", "chave": "Potência"},
    "veneravel_mestre": {"nome": "Venerável Mestre (Sim/Não)", "chave": "Venerável Mestre"},
}

# ============================================
# INÍCIO DO AJUSTE DE CADASTRO
# ============================================

async def editar_perfil_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Inicia o ajuste dos dados do Irmão.
    """
    user_id = update.effective_user.id
    membro = buscar_membro(user_id)
    
    if not membro:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "Saudações, Irmão. Identificamos que ainda não possuís cadastro. Por favor, utilize o comando /start para iniciar nossa caminhada."
        )
        return ConversationHandler.END

    context.user_data["perfil_dados"] = membro

    botoes = []
    for campo_id, campo_info in CAMPOS_EDITAVEIS_PERFIL.items():
        valor_atual = membro.get(campo_info["chave"], "Não informado")
        botoes.append([
            InlineKeyboardButton(
                f"📝 {campo_info['nome']}: {str(valor_atual)[:25]}",
                callback_data=f"editar_campo_perfil|{campo_id}"
            )
        ])

    botoes.append([InlineKeyboardButton("🔙 Retornar ao Menu", callback_data="menu_principal")])
    teclado = InlineKeyboardMarkup(botoes)

    await navegar_para(
        update, context,
        "Ajustar Cadastro",
        "Estimado Irmão, selecione qual informação de seu cadastro desejas retificar para que nossos registros permaneçam exatos:",
        teclado
    )
    return SELECIONAR_CAMPO

# ============================================
# SELEÇÃO DO CAMPO A RETIFICAR
# ============================================

async def selecionar_campo_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Prepara o bot para receber a nova informação.
    """
    query = update.callback_query
    campo_id = query.data.split("|")[1]
    campo_info = CAMPOS_EDITAVEIS_PERFIL.get(campo_id)

    if not campo_info:
        return ConversationHandler.END

    context.user_data["editando_campo_perfil"] = campo_id
    membro = context.user_data.get("perfil_dados", {})
    valor_atual = membro.get(campo_info["chave"], "Vazio")

    await navegar_para(
        update, context,
        f"Retificar {campo_info['nome']}",
        f"✏️ *Retificação de {campo_info['nome']}*\n\n"
        f"Informação atual: `{valor_atual}`\n\n"
        f"Por favor, escreva o novo dado abaixo (ou utilize /cancelar para manter como está):",
        None
    )
    return NOVO_VALOR

# ============================================
# PROCESSAMENTO DA NOVA INFORMAÇÃO
# ============================================

async def receber_novo_valor_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Recebe o novo dado e o mantém acoberto no sistema.
    """
    novo_valor = update.message.text.strip()
    campo_id = context.user_data.get("editando_campo_perfil")
    campo_info = CAMPOS_EDITAVEIS_PERFIL.get(campo_id)
    
    if not campo_info:
        return ConversationHandler.END

    # Validação simples para Venerável Mestre
    if campo_id == "veneravel_mestre":
        if novo_valor.lower() not in ["sim", "não", "s", "n"]:
            await update.message.reply_text("Irmão, para este campo, por favor responda apenas com 'Sim' ou 'Não'.")
            return NOVO_VALOR

    user_id = update.effective_user.id
    sucesso = atualizar_membro(user_id, {campo_info["chave"]: novo_valor}, preservar_nivel=True)

    if sucesso:
        await update.message.reply_text(
            f"✅ Justo e Perfeito! O campo *{campo_info['nome']}* foi atualizado e permanece acoberto em nossos registros.\n\n"
            f"Utilize o menu acima para navegar."
        )
    else:
        await update.message.reply_text("Houve um percalço ao atualizar seus dados. Por favor, tente novamente em alguns instantes.")

    # Limpeza de sessão
    context.user_data.pop("editando_campo_perfil", None)
    context.user_data.pop("perfil_dados", None)

    return ConversationHandler.END

# ============================================
# CANCELAMENTO FRATERNO
# ============================================

async def cancelar_edicao_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Interrompe o processo de edição.
    """
    msg = "A retificação foi interrompida. Seus dados permanecem inalterados e acobertos."
    
    if update.message:
        await update.message.reply_text(msg)
    elif update.callback_query:
        await _enviar_ou_editar_mensagem(context, update.effective_user.id, TIPO_RESULTADO, msg)
    
    context.user_data.clear()
    return ConversationHandler.END

# ============================================
# HANDLER DE CONVERSAÇÃO
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