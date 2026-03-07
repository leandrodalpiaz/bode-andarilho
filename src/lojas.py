# src/lojas.py
# ============================================
# BODE ANDARILHO - GERENCIAMENTO DE LOJAS
# ============================================
# 
# Este módulo permite que secretários e administradores
# pré-cadastrem os dados fixos de suas lojas para usar
# como atalho na criação de novos eventos.
# 
# Funcionalidades:
# - Cadastro de nova loja (nome, número, rito, potência, endereço)
# - Listagem das lojas cadastradas
# - Integração com o cadastro de eventos para pré-preenchimento
# 
# Todas as funções que exibem resultados utilizam o sistema de
# navegação do bot.py para manter a consistência da interface.
# 
# ============================================

from __future__ import annotations

import logging
from typing import Any, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from src.sheets import listar_lojas, cadastrar_loja, excluir_loja
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

# Estados da conversação para cadastro de loja
NOME, NUMERO, RITO, POTENCIA, ENDERECO, CONFIRMAR = range(6)


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
# MENU PRINCIPAL DE LOJAS
# ============================================

async def menu_lojas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Menu principal para gerenciar lojas.
    Exibe opções de cadastrar nova loja ou listar as existentes.
    """
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Apenas secretários e administradores podem acessar esta função."
        )
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Cadastrar nova loja", callback_data="loja_cadastrar")],
        [InlineKeyboardButton("📋 Listar minhas lojas", callback_data="loja_listar")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="area_secretario" if nivel == "2" else "area_admin")],
    ])

    await navegar_para(
        update, context,
        "Gerenciamento de Lojas",
        "🏛️ *Gerenciamento de Lojas*\n\n"
        "Aqui você pode cadastrar os dados fixos da sua loja "
        "para usar como atalho ao criar novos eventos.",
        teclado
    )


# ============================================
# LISTAR LOJAS CADASTRADAS
# ============================================

async def listar_lojas_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista as lojas cadastradas pelo secretário."""
    user_id = update.effective_user.id
    lojas = listar_lojas(user_id)

    if not lojas:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Cadastrar nova loja", callback_data="loja_cadastrar")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu_lojas")],
        ])
        await navegar_para(
            update, context,
            "Gerenciamento de Lojas > Minhas Lojas",
            "📋 *Minhas Lojas*\n\nVocê ainda não cadastrou nenhuma loja.",
            teclado
        )
        return

    texto = "📋 *Minhas Lojas*\n\n"
    for loja in lojas:
        texto += (
            f"🏛 *{loja.get('Nome da Loja')}*"
            f"{' ' + str(loja.get('Número')) if loja.get('Número') else ''}\n"
            f"📜 Rito: {loja.get('Rito')}\n"
            f"⚜️ Potência: {loja.get('Potência')}\n"
            f"📍 Endereço: {loja.get('Endereço')}\n"
            f"━━━━━━━━━━━━━━━━\n"
        )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Cadastrar nova", callback_data="loja_cadastrar")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu_lojas")],
    ])

    await navegar_para(
        update, context,
        "Gerenciamento de Lojas > Minhas Lojas",
        texto,
        teclado
    )


# ============================================
# CADASTRO DE NOVA LOJA (CONVERSATION HANDLER)
# ============================================

async def cadastrar_loja_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o cadastro de uma nova loja."""
    query = update.callback_query
    if query:
        await query.answer("🏛️ Iniciando cadastro...")
    
    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _enviar_ou_editar_mensagem(
            context, user_id, TIPO_RESULTADO,
            "⛔ Permissão negada."
        )
        return ConversationHandler.END

    context.user_data["nova_loja"] = {}
    
    await navegar_para(
        update, context,
        "Cadastro de Loja",
        "🏛️ *Cadastro de Loja*\n\nQual o *nome da loja*?",
        InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]])
    )
    return NOME


async def receber_nome_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o nome da loja."""
    nome = update.message.text.strip()
    if len(nome) < 2:
        await update.message.reply_text("❌ Nome muito curto. Digite novamente:")
        return NOME

    context.user_data["nova_loja"]["nome"] = nome
    
    await update.message.reply_text(
        "🔢 *Número da loja* (Digite 0 se não houver)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
    )
    return NUMERO


async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o número da loja."""
    numero = update.message.text.strip()
    if not numero.isdigit() and numero != "0":
        await update.message.reply_text("❌ Digite apenas números (ou 0):")
        return NUMERO

    context.user_data["nova_loja"]["numero"] = numero
    
    await update.message.reply_text(
        "📜 *Rito*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
    )
    return RITO


async def receber_rito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o rito."""
    rito = update.message.text.strip()
    if len(rito) < 2:
        await update.message.reply_text("❌ Rito muito curto. Digite novamente:")
        return RITO

    context.user_data["nova_loja"]["rito"] = rito
    
    await update.message.reply_text(
        "⚜️ *Potência*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
    )
    return POTENCIA


async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a potência."""
    potencia = update.message.text.strip()
    if len(potencia) < 2:
        await update.message.reply_text("❌ Potência muito curta. Digite novamente:")
        return POTENCIA

    context.user_data["nova_loja"]["potencia"] = potencia
    
    await update.message.reply_text(
        "📍 *Endereço* da loja?\n"
        "(Pode ser texto ou link do Google Maps)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
    )
    return ENDERECO


async def receber_endereco_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o endereço e mostra resumo para confirmação."""
    endereco = update.message.text.strip()
    if len(endereco) < 3:
        await update.message.reply_text("❌ Endereço muito curto. Digite novamente:")
        return ENDERECO

    context.user_data["nova_loja"]["endereco"] = endereco
    dados = context.user_data["nova_loja"]

    resumo = (
        f"🏛️ *Confirme os dados da loja:*\n\n"
        f"*Nome:* {dados['nome']}\n"
        f"*Número:* {dados['numero']}\n"
        f"*Rito:* {dados['rito']}\n"
        f"*Potência:* {dados['potencia']}\n"
        f"*Endereço:* {dados['endereco']}\n\n"
        f"Tudo correto?"
    )

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sim, cadastrar", callback_data="confirmar_cadastro_loja")],
        [InlineKeyboardButton("🔄 Recomeçar", callback_data="loja_cadastrar")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")],
    ])

    await update.message.reply_text(resumo, parse_mode="Markdown", reply_markup=teclado)
    return CONFIRMAR


# ============================================
# CONFIRMAÇÃO DE CADASTRO DE LOJA (CORRIGIDO)
# ============================================

async def confirmar_cadastro_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma e salva a loja na planilha."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Responde ao callback imediatamente para evitar timeout
    await query.answer("✅ Processando...")

    # Recupera os dados do user_data
    dados = context.user_data.get("nova_loja", {})

    if not dados:
        logger.error(f"Erro: dados não encontrados para usuário {user_id}")
        await navegar_para(
            update, context,
            "Cadastro de Loja",
            "❌ *Erro: dados não encontrados.*\n\nTente novamente.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🏛️ Voltar ao menu de lojas", callback_data="menu_lojas")
            ]])
        )
        return ConversationHandler.END

    # Tenta cadastrar na planilha
    sucesso = cadastrar_loja(user_id, dados)

    if sucesso:
        logger.info(f"Loja cadastrada com sucesso para usuário {user_id}: {dados.get('nome')}")
        await navegar_para(
            update, context,
            "Cadastro de Loja",
            "✅ *Loja cadastrada com sucesso!*\n\n"
            "Agora você pode usar este cadastro como atalho ao criar novos eventos.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🏛️ Gerenciar lojas", callback_data="menu_lojas")
            ]])
        )
    else:
        logger.error(f"Erro ao cadastrar loja para usuário {user_id}: {dados.get('nome')}")
        await navegar_para(
            update, context,
            "Cadastro de Loja",
            "❌ *Erro ao cadastrar loja.*\n\n"
            "Tente novamente mais tarde.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🏛️ Voltar ao menu de lojas", callback_data="menu_lojas")
            ]])
        )

    # Limpa os dados da sessão
    context.user_data.pop("nova_loja", None)
    return ConversationHandler.END


async def cancelar_cadastro_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o cadastro de loja."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query:
        await query.answer()
        await navegar_para(
            update, context,
            "Cadastro de Loja",
            "Cadastro cancelado.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🏛️ Voltar ao menu de lojas", callback_data="menu_lojas")
            ]])
        )
    else:
        if update.message:
            await update.message.reply_text("Cadastro cancelado.")

    context.user_data.pop("nova_loja", None)
    return ConversationHandler.END


# ============================================
# CONVERSATION HANDLER
# ============================================

cadastro_loja_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(cadastrar_loja_inicio, pattern="^loja_cadastrar$")],
    states={
        NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome_loja)],
        NUMERO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_numero_loja)],
        RITO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_rito)],
        POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_potencia)],
        ENDERECO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_endereco_loja)],
        CONFIRMAR: [
            CallbackQueryHandler(confirmar_cadastro_loja, pattern="^confirmar_cadastro_loja$"),
            CallbackQueryHandler(cancelar_cadastro_loja, pattern="^cancelar_cadastro_loja$"),
            CallbackQueryHandler(cadastrar_loja_inicio, pattern="^loja_cadastrar$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_cadastro_loja),
        CallbackQueryHandler(cancelar_cadastro_loja, pattern="^cancelar_cadastro_loja$"),
    ],
    name="cadastro_loja_handler",
    persistent=False,
)


# ============================================
# HANDLERS SIMPLES (PARA REGISTRO NO MAIN.PY)
# ============================================

# Estes handlers são referenciados no main.py
listar_lojas_handler_cb = CallbackQueryHandler(listar_lojas_handler, pattern="^loja_listar$")
menu_lojas_handler = CallbackQueryHandler(menu_lojas, pattern="^menu_lojas$")