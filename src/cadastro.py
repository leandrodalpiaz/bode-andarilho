# src/cadastro.py
from __future__ import annotations

import logging
import re
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.sheets import buscar_membro, cadastrar_membro

logger = logging.getLogger(__name__)

# -------------------------
# Estados (ConversationHandler)
# -------------------------
NOME, DATA_NASC, GRAU, VM, LOJA, NUMERO_LOJA, ORIENTE, POTENCIA, CONFIRMAR = range(9)

# -------------------------
# Constantes UX
# -------------------------
GRAUS_OPCOES = [
    "Aprendiz",
    "Companheiro",
    "Mestre",
    "Mestre Instalado",
]

VM_SIM = "Sim"
VM_NAO = "Não"


# -------------------------
# Helpers de UX
# -------------------------
def _preservar_e_limpar_user_data(context: ContextTypes.DEFAULT_TYPE, preservar: set[str] | None = None):
    preservar = preservar or set()
    keep = {k: context.user_data.get(k) for k in preservar if k in context.user_data}
    context.user_data.clear()
    context.user_data.update(keep)


def _teclado_nav(estado_voltar: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{estado_voltar}"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancelar"),
            ]
        ]
    )


def _teclado_confirmar() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirmar cadastro", callback_data="confirmar_cadastro")],
            [
                InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{POTENCIA}"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancelar"),
            ],
        ]
    )


def _teclado_inicio(cadastrado: bool) -> InlineKeyboardMarkup:
    if cadastrado:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✏️ Editar meu cadastro", callback_data="editar_cadastro")],
                [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
            ]
        )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧾 Iniciar cadastro", callback_data="iniciar_cadastro")],
            [InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")],
        ]
    )


def _teclado_grau() -> InlineKeyboardMarkup:
    botoes = [[InlineKeyboardButton(g, callback_data=f"set_grau|{g}")] for g in GRAUS_OPCOES]
    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{DATA_NASC}")])
    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(botoes)


def _teclado_vm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Sim", callback_data=f"set_vm|{VM_SIM}")],
            [InlineKeyboardButton("Não", callback_data=f"set_vm|{VM_NAO}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{GRAU}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
    )


def _validar_data_nasc(texto: str) -> bool:
    s = (texto or "").strip()
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
        return False
    try:
        datetime.strptime(s, "%d/%m/%Y")
        return True
    except Exception:
        return False


def _validar_numero_loja(texto: str) -> bool:
    s = (texto or "").strip()
    if s == "":
        return False
    return bool(re.fullmatch(r"\d+", s))


async def _prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, estado: int):
    """
    Mostra o texto correto para cada estado e o teclado adequado.
    """
    textos = {
        NOME: "Envie seu *nome completo*:",
        DATA_NASC: "Envie sua *data de nascimento* (DD/MM/AAAA):",
        GRAU: "Selecione seu *grau*:",
        VM: "Você é *Venerável Mestre*?",
        LOJA: "Informe o *nome da sua loja*:",
        NUMERO_LOJA: "Informe o *número da sua loja* (somente números, ou 0):",
        ORIENTE: "Informe seu *Oriente*:",
        POTENCIA: "Informe sua *Potência*:",
    }

    context.user_data["estado_atual"] = estado

    # Define teclado por estado
    if estado == GRAU:
        reply_markup = _teclado_grau()
    elif estado == VM:
        reply_markup = _teclado_vm()
    else:
        # voltar leva para o estado anterior (aproximação)
        voltar_para = max(NOME, estado - 1)
        reply_markup = _teclado_nav(voltar_para)

    text = textos.get(estado, "Envie a informação:")

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


# -------------------------
# Entrada /start (privado)
# -------------------------
async def cadastro_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usado quando o usuário entra no privado.
    Se já cadastrado: oferece editar.
    Se não: oferece iniciar.
    """
    try:
        if update.effective_chat and update.effective_chat.type != "private":
            return

        tid = update.effective_user.id
        membro = buscar_membro(tid)
        cadastrado = bool(membro)

        msg = (
            "🧾 *Cadastro*\n\n"
            + ("Você já possui cadastro. Selecione uma opção:" if cadastrado else "Você ainda não possui cadastro. Selecione uma opção:")
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_teclado_inicio(cadastrado))
    except Exception as e:
        logger.error(f"Erro em cadastro_start: {e}\n{traceback.format_exc()}")


async def iniciar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    # preserva pos_cadastro se existir
    pos = context.user_data.get("pos_cadastro")
    _preservar_e_limpar_user_data(context, preservar={"pos_cadastro"})
    if pos:
        context.user_data["pos_cadastro"] = pos

    await query.edit_message_text(
        "Vamos começar seu cadastro.\n\nEnvie seu *nome completo*:",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(NOME),
    )
    context.user_data["estado_atual"] = NOME
    return NOME


async def editar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    tid = update.effective_user.id
    membro = buscar_membro(tid) or {}

    # carrega dados atuais como baseline
    context.user_data["cadastro_nome"] = str(membro.get("Nome") or "").strip()
    context.user_data["cadastro_data_nasc"] = str(membro.get("Data nasc.") or membro.get("Data nasc", "") or membro.get("Data Nasc.", "") or "").strip()
    context.user_data["cadastro_grau"] = str(membro.get("Grau") or "").strip()
    context.user_data["cadastro_vm"] = str(membro.get("Venerável Mestre") or membro.get("Veneravel Mestre") or "").strip()
    context.user_data["cadastro_loja"] = str(membro.get("Loja") or "").strip()
    context.user_data["cadastro_numero_loja"] = str(membro.get("Número da loja") or "").strip()
    context.user_data["cadastro_oriente"] = str(membro.get("Oriente") or "").strip()
    context.user_data["cadastro_potencia"] = str(membro.get("Potência") or "").strip()

    await query.edit_message_text(
        "✏️ *Editar cadastro*\n\nEnvie seu *nome completo*:",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(NOME),
    )
    context.user_data["estado_atual"] = NOME
    return NOME


async def continuar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Mantido por compatibilidade com seu handler antigo.
    Retoma do estado salvo.
    """
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    estado = context.user_data.get("estado_atual", NOME)
    await _prompt(update, context, int(estado))
    return int(estado)


# -------------------------
# Navegação (voltar/cancelar)
# -------------------------
async def navegacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    data = query.data or ""

    if data == "cancelar":
        return await cancelar_cadastro(update, context)

    if data.startswith("voltar|"):
        try:
            estado = int(data.split("|", 1)[1])
        except Exception:
            estado = NOME

        await _prompt(update, context, estado)
        return estado

    return ConversationHandler.END


# -------------------------
# Recebedores de texto (estados textuais)
# -------------------------
async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_nome"] = (update.message.text or "").strip()
    await _prompt(update, context, DATA_NASC)
    return DATA_NASC


async def receber_data_nasc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (update.message.text or "").strip()
    if not _validar_data_nasc(texto):
        await update.message.reply_text(
            "Data inválida. Envie no formato *DD/MM/AAAA*.",
            parse_mode="Markdown",
            reply_markup=_teclado_nav(DATA_NASC),
        )
        context.user_data["estado_atual"] = DATA_NASC
        return DATA_NASC

    context.user_data["cadastro_data_nasc"] = texto
    await _prompt(update, context, GRAU)
    return GRAU


async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_loja"] = (update.message.text or "").strip()
    await _prompt(update, context, NUMERO_LOJA)
    return NUMERO_LOJA


async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (update.message.text or "").strip()
    if not _validar_numero_loja(texto):
        await update.message.reply_text(
            "Número inválido. Envie apenas *números* (ex.: 270) ou *0*.",
            parse_mode="Markdown",
            reply_markup=_teclado_nav(NUMERO_LOJA),
        )
        context.user_data["estado_atual"] = NUMERO_LOJA
        return NUMERO_LOJA

    context.user_data["cadastro_numero_loja"] = texto
    await _prompt(update, context, ORIENTE)
    return ORIENTE


async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_oriente"] = (update.message.text or "").strip()
    await _prompt(update, context, POTENCIA)
    return POTENCIA


async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_potencia"] = (update.message.text or "").strip()
    context.user_data["estado_atual"] = CONFIRMAR
    await mostrar_resumo(update, context)
    return CONFIRMAR


# -------------------------
# Recebedores por botões (GRAU e VM)
# -------------------------
async def set_grau_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    # data: set_grau|Aprendiz
    try:
        _, grau = (query.data or "").split("|", 1)
    except Exception:
        grau = ""

    grau = grau.strip()
    if grau not in GRAUS_OPCOES:
        await query.edit_message_text(
            "Seleção inválida. Selecione seu *grau*:",
            parse_mode="Markdown",
            reply_markup=_teclado_grau(),
        )
        context.user_data["estado_atual"] = GRAU
        return GRAU

    context.user_data["cadastro_grau"] = grau
    await query.edit_message_text(
        "Você é *Venerável Mestre*?",
        parse_mode="Markdown",
        reply_markup=_teclado_vm(),
    )
    context.user_data["estado_atual"] = VM
    return VM


async def set_vm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    # data: set_vm|Sim
    try:
        _, vm = (query.data or "").split("|", 1)
    except Exception:
        vm = ""

    vm = vm.strip()
    if vm not in (VM_SIM, VM_NAO):
        await query.edit_message_text(
            "Seleção inválida. Você é *Venerável Mestre*?",
            parse_mode="Markdown",
            reply_markup=_teclado_vm(),
        )
        context.user_data["estado_atual"] = VM
        return VM

    context.user_data["cadastro_vm"] = vm
    await query.edit_message_text(
        "Informe o *nome da sua loja*:",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(LOJA),
    )
    context.user_data["estado_atual"] = LOJA
    return LOJA


# -------------------------
# Resumo e confirmação
# -------------------------
async def mostrar_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = context.user_data.get("cadastro_nome", "")
    data_nasc = context.user_data.get("cadastro_data_nasc", "")
    grau = context.user_data.get("cadastro_grau", "")
    vm = context.user_data.get("cadastro_vm", "")
    loja = context.user_data.get("cadastro_loja", "")
    numero = context.user_data.get("cadastro_numero_loja", "")
    oriente = context.user_data.get("cadastro_oriente", "")
    potencia = context.user_data.get("cadastro_potencia", "")

    resumo = (
        "📋 *Resumo do cadastro*\n\n"
        f"Nome: {nome}\n"
        f"Data nasc.: {data_nasc}\n"
        f"Grau: {grau}\n"
        f"Venerável Mestre: {vm}\n"
        f"Loja: {loja} {numero}\n"
        f"Oriente: {oriente}\n"
        f"Potência: {potencia}\n\n"
        "*Tudo correto?*"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(resumo, parse_mode="Markdown", reply_markup=_teclado_confirmar())
    else:
        await update.message.reply_text(resumo, parse_mode="Markdown", reply_markup=_teclado_confirmar())


async def confirmar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    try:
        dados_membro: Dict[str, Any] = {
            "nome": context.user_data.get("cadastro_nome", ""),
            "data_nasc": context.user_data.get("cadastro_data_nasc", ""),
            "grau": context.user_data.get("cadastro_grau", ""),
            "loja": context.user_data.get("cadastro_loja", ""),
            "numero_loja": context.user_data.get("cadastro_numero_loja", ""),
            "oriente": context.user_data.get("cadastro_oriente", ""),
            "potencia": context.user_data.get("cadastro_potencia", ""),
            "telegram_id": update.effective_user.id,
            "cargo": "",
            "veneravel_mestre": context.user_data.get("cadastro_vm", ""),
        }

        # Salva (cadastrar_membro já faz update se existir, sem mexer em Nivel)
        cadastrar_membro(dados_membro)

        # preserva pos_cadastro
        pos = context.user_data.get("pos_cadastro")
        _preservar_e_limpar_user_data(context, preservar={"pos_cadastro"})
        if pos:
            context.user_data["pos_cadastro"] = pos

        # executa ação pós-cadastro se existir
        if pos and isinstance(pos, dict) and pos.get("acao") == "confirmar":
            try:
                from src.eventos import iniciar_confirmacao_presenca_pos_cadastro

                await iniciar_confirmacao_presenca_pos_cadastro(update, context, pos)
                context.user_data.pop("pos_cadastro", None)
            except Exception as e:
                logger.error(f"Erro no pos_cadastro: {e}\n{traceback.format_exc()}")

        await query.edit_message_text(
            "✅ *Cadastro realizado com sucesso!*\n\nUse /start para acessar o menu principal.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Erro em confirmar_cadastro: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("❌ Ocorreu um erro ao salvar seus dados. Tente novamente mais tarde.")
        return ConversationHandler.END


async def cancelar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                "Cadastro cancelado. Você pode iniciar novamente com /start."
            )
        elif update.message:
            await update.message.reply_text("Cadastro cancelado. Você pode iniciar novamente com /start.")
    except Exception as e:
        logger.error(f"Erro em cancelar_cadastro: {e}\n{traceback.format_exc()}")

    _preservar_e_limpar_user_data(context, preservar={"pos_cadastro"})
    return ConversationHandler.END


# -------------------------
# Handler
# -------------------------
cadastro_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", cadastro_start),
        CallbackQueryHandler(iniciar_cadastro_callback, pattern=r"^iniciar_cadastro$"),
        CallbackQueryHandler(continuar_cadastro_callback, pattern=r"^continuar_cadastro$"),
        CallbackQueryHandler(editar_cadastro_callback, pattern=r"^editar_cadastro$"),
    ],
    states={
        NOME: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_nome),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        DATA_NASC: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_data_nasc),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        GRAU: [
            CallbackQueryHandler(set_grau_callback, pattern=r"^set_grau\|"),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        VM: [
            CallbackQueryHandler(set_vm_callback, pattern=r"^set_vm\|"),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        LOJA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_loja),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        NUMERO_LOJA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMAND, receber_numero_loja),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        ORIENTE: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_oriente),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        POTENCIA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_potencia),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
        CONFIRMAR: [
            CallbackQueryHandler(confirmar_cadastro, pattern=r"^confirmar_cadastro$"),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_cadastro),
        CallbackQueryHandler(navegacao_callback, pattern=r"^(voltar\|\d+|cancelar)$"),
    ],
    allow_reentry=True,
    name="cadastro_handler",
    persistent=False,
)