# src/lojas.py
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

logger = logging.getLogger(__name__)

# Estados da conversação
NOME, NUMERO, RITO, POTENCIA, ENDERECO, CONFIRMAR = range(6)


async def _safe_edit(query, text: str, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


# =========================
# Menu principal de lojas
# =========================
async def menu_lojas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu principal para gerenciar lojas."""
    query = update.callback_query
    if not query:
        return
    await query.answer("🏛️ Carregando lojas...")

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _safe_edit(query, "⛔ Apenas secretários e administradores podem acessar esta função.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Cadastrar nova loja", callback_data="loja_cadastrar")],
        [InlineKeyboardButton("📋 Listar minhas lojas", callback_data="loja_listar")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="area_secretario" if nivel == "2" else "area_admin")],
    ])

    await _safe_edit(
        query,
        "🏛️ *Gerenciamento de Lojas*\n\n"
        "Aqui você pode cadastrar os dados fixos da sua loja "
        "para usar como atalho ao criar novos eventos.",
        parse_mode="Markdown",
        reply_markup=teclado,
    )


async def listar_lojas_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista as lojas cadastradas pelo secretário."""
    query = update.callback_query
    if not query:
        return
    await query.answer("📋 Buscando suas lojas...")

    user_id = update.effective_user.id
    lojas = listar_lojas(user_id)

    if not lojas:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Cadastrar nova loja", callback_data="loja_cadastrar")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_lojas")],
        ])
        await _safe_edit(
            query,
            "📋 *Minhas Lojas*\n\n"
            "Você ainda não cadastrou nenhuma loja.",
            parse_mode="Markdown",
            reply_markup=teclado,
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
        [InlineKeyboardButton("⬅️ Voltar", callback_data="menu_lojas")],
    ])

    await _safe_edit(query, texto, parse_mode="Markdown", reply_markup=teclado)


# =========================
# Cadastro de nova loja (ConversationHandler)
# =========================
async def cadastrar_loja_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o cadastro de uma nova loja."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer("🏛️ Iniciando cadastro de loja...")

    user_id = update.effective_user.id
    nivel = get_nivel(user_id)
    
    if nivel not in ["2", "3"]:
        await _safe_edit(query, "⛔ Permissão negada.")
        return ConversationHandler.END

    context.user_data["nova_loja"] = {}
    
    await _safe_edit(
        query,
        "🏛️ *Cadastro de Loja*\n\n"
        "Qual o *nome da loja*?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_cadastro_loja")
        ]]),
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
        "Qual o *número da loja*? (Digite 0 se não houver)",
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
        "Qual o *Rito*?",
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
        "Qual a *Potência*?",
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
        "Qual o *Endereço* da loja?\n"
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


async def confirmar_cadastro_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma e salva a loja na planilha."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer("✅ Salvando loja...")

    user_id = update.effective_user.id
    dados = context.user_data.get("nova_loja", {})

    if not dados:
        await _safe_edit(query, "❌ Erro: dados não encontrados.")
        return ConversationHandler.END

    sucesso = cadastrar_loja(user_id, dados)

    if sucesso:
        await _safe_edit(
            query,
            "✅ *Loja cadastrada com sucesso!*\n\n"
            "Agora você pode usar este cadastro como atalho ao criar novos eventos.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏛️ Gerenciar lojas", callback_data="menu_lojas")
            ]]),
        )
    else:
        await _safe_edit(
            query,
            "❌ *Erro ao cadastrar loja.*\n\n"
            "Tente novamente mais tarde.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏛️ Voltar", callback_data="menu_lojas")
            ]]),
        )

    context.user_data.pop("nova_loja", None)
    return ConversationHandler.END


async def cancelar_cadastro_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o cadastro de loja."""
    query = update.callback_query
    if query:
        await query.answer("❌ Cadastro cancelado")
        await _safe_edit(
            query,
            "Cadastro cancelado.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏛️ Voltar ao menu de lojas", callback_data="menu_lojas")
            ]]),
        )
    else:
        if update.message:
            await update.message.reply_text("Cadastro cancelado.")

    context.user_data.pop("nova_loja", None)
    return ConversationHandler.END


# =========================
# ConversationHandler
# =========================
cadastro_loja_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(cadastrar_loja_inicio, pattern="^loja_cadastrar$")],
    states={
        NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome_loja)],
        NUMERO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_numero_loja)],
        RITO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_rito)],
        POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_potencia)],
        ENDERECO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_endereco_loja)],
        CONFIRMAR: [CallbackQueryHandler(confirmar_cadastro_loja, pattern="^confirmar_cadastro_loja$")],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_cadastro_loja),
        CallbackQueryHandler(cancelar_cadastro_loja, pattern="^cancelar_cadastro_loja$"),
    ],
)

# Handlers simples
listar_lojas_handler_cb = CallbackQueryHandler(listar_lojas_handler, pattern="^loja_listar$")
menu_lojas_handler = CallbackQueryHandler(menu_lojas, pattern="^menu_lojas$")