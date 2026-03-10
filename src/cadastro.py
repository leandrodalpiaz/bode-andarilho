# src/cadastro.py
# ============================================
# BODE ANDARILHO - CADASTRO DE MEMBROS
# ============================================
# 
# Este módulo gerencia o cadastro de novos membros e a edição
# do próprio cadastro pelo usuário.
# 
# Funcionalidades:
# - Cadastro completo com validação de dados
# - Edição de cadastro existente
# - Navegação com botões Voltar/Cancelar
# - Integração com confirmação de presença (pos_cadastro)
# 
# Utiliza um ConversationHandler com 9 estados sequenciais.
# 
# ============================================

from __future__ import annotations

import logging
import re
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.sheets_supabase import buscar_membro, cadastrar_membro
from src.bot import (
    navegar_para,
    _enviar_ou_editar_mensagem,
    TIPO_RESULTADO
)

logger = logging.getLogger(__name__)

# ============================================
# CONSTANTES E CONFIGURAÇÕES
# ============================================

# Estados da conversação
NOME, DATA_NASC, GRAU, VM, LOJA, NUMERO_LOJA, ORIENTE, POTENCIA, CONFIRMAR = range(9)

# Opções fixas
GRAUS_OPCOES = [
    "Aprendiz",
    "Companheiro",
    "Mestre",
    "Mestre Instalado",
]

VM_SIM = "Sim"
VM_NAO = "Não"


# ============================================
# FUNÇÕES AUXILIARES DE INTERFACE
# ============================================

def _teclado_nav(estado_voltar: int) -> InlineKeyboardMarkup:
    """Cria teclado com botões Voltar e Cancelar."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{estado_voltar}"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancelar"),
            ]
        ]
    )


def _teclado_confirmar() -> InlineKeyboardMarkup:
    """Cria teclado para tela de confirmação."""
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
    """Cria teclado da tela inicial de cadastro."""
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
    """Cria teclado com opções de grau."""
    botoes = [[InlineKeyboardButton(g, callback_data=f"set_grau|{g}")] for g in GRAUS_OPCOES]
    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{DATA_NASC}")])
    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(botoes)


def _teclado_vm() -> InlineKeyboardMarkup:
    """Cria teclado para pergunta de Venerável Mestre."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Sim", callback_data=f"set_vm|{VM_SIM}")],
            [InlineKeyboardButton("Não", callback_data=f"set_vm|{VM_NAO}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{GRAU}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
    )


def _validar_data_nasc(texto: str) -> bool:
    """Valida se a data está no formato DD/MM/AAAA."""
    s = (texto or "").strip()
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
        return False
    try:
        datetime.strptime(s, "%d/%m/%Y")
        return True
    except Exception:
        return False


def _validar_numero_loja(texto: str) -> bool:
    """Valida se o número da loja contém apenas dígitos."""
    s = (texto or "").strip()
    if s == "":
        return False
    return bool(re.fullmatch(r"\d+", s))


def _resumo_cadastro(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Gera resumo dos dados para confirmação."""
    nome = (context.user_data.get("cadastro_nome") or "").strip()
    data_nasc = (context.user_data.get("cadastro_data_nasc") or "").strip()
    grau = (context.user_data.get("cadastro_grau") or "").strip()
    vm = (context.user_data.get("cadastro_vm") or "").strip()
    loja = (context.user_data.get("cadastro_loja") or "").strip()
    numero_loja = (context.user_data.get("cadastro_numero_loja") or "").strip()
    oriente = (context.user_data.get("cadastro_oriente") or "").strip()
    potencia = (context.user_data.get("cadastro_potencia") or "").strip()

    numero_fmt = f" - Nº {numero_loja}" if numero_loja and numero_loja not in ("0", "") else ""

    return (
        "*Confira seus dados:*\n\n"
        f"👤 *Nome:* {nome}\n"
        f"🎂 *Nascimento:* {data_nasc}\n"
        f"🔺 *Grau:* {grau}\n"
        f"🔨 *Venerável Mestre:* {vm}\n"
        f"🏛 *Loja:* {loja}{numero_fmt}\n"
        f"📍 *Oriente:* {oriente}\n"
        f"⚜️ *Potência:* {potencia}\n\n"
        "_Seus dados serão mantidos em absoluto sigilo._"
    )


# ============================================
# FUNÇÃO PRINCIPAL DE ENTRADA
# ============================================

async def cadastro_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ponto de entrada para o cadastro.
    
    Fluxo:
    - Em grupo: orienta a usar o privado
    - Em privado: se cadastrado, oferece editar; se não, iniciar
    """
    try:
        # Se veio do grupo, orienta
        if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
            if update.message:
                await update.message.reply_text(
                    "🔒 Para realizar seu cadastro, fale comigo no privado.\n\n"
                    "Clique aqui: @BodeAndarilhoBot e envie /start"
                )
            return

        # Aqui já é privado
        telegram_id = update.effective_user.id
        membro = buscar_membro(telegram_id)
        cadastrado = bool(membro)

        texto = (
            "👤 *Cadastro*\n\n"
            "Aqui você pode iniciar ou editar seu cadastro.\n"
            "Se estiver tudo certo, volte ao menu principal.\n\n"
            "_Lembre-se: suas informações estão sob a proteção do sigilo maçônico._"
        )

        if update.callback_query:
            await update.callback_query.edit_message_text(
                texto,
                parse_mode="Markdown",
                reply_markup=_teclado_inicio(cadastrado)
            )
        elif update.message:
            await update.message.reply_text(
                texto,
                parse_mode="Markdown",
                reply_markup=_teclado_inicio(cadastrado)
            )
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Erro em cadastro_start: {e}\n{traceback.format_exc()}")
        if update.message:
            await update.message.reply_text("❌ Ocorreu um erro. Tente novamente em instantes.")
        return ConversationHandler.END


# ============================================
# INICIAR / CONTINUAR / EDITAR
# ============================================

async def iniciar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia um novo cadastro."""
    query = update.callback_query
    await query.answer()

    # Preserva pos_cadastro (confirmação pendente)
    pos = context.user_data.get("pos_cadastro")
    context.user_data.clear()
    if pos:
        context.user_data["pos_cadastro"] = pos

    await navegar_para(
        update, context,
        "Cadastro",
        "Envie seu *nome completo*:",
        _teclado_nav(NOME)
    )
    return NOME


async def editar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia edição de cadastro existente."""
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    # Preserva pos_cadastro
    pos = context.user_data.get("pos_cadastro")
    context.user_data.clear()
    if pos:
        context.user_data["pos_cadastro"] = pos

    if not membro:
        await _enviar_ou_editar_mensagem(
            context, telegram_id, TIPO_RESULTADO,
            "Você ainda não tem cadastro. Vamos iniciar agora.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🧾 Iniciar cadastro", callback_data="iniciar_cadastro")]])
        )
        return ConversationHandler.END

    # Pré-preenche com dados existentes
    context.user_data["cadastro_nome"] = (membro.get("Nome") or membro.get("nome") or "").strip()
    context.user_data["cadastro_data_nasc"] = (membro.get("Data de nascimento") or membro.get("data_nasc") or "").strip()
    context.user_data["cadastro_grau"] = (membro.get("Grau") or membro.get("grau") or "").strip()
    context.user_data["cadastro_vm"] = (membro.get("Venerável Mestre") or membro.get("veneravel_mestre") or membro.get("vm") or "").strip()
    context.user_data["cadastro_loja"] = (membro.get("Loja") or membro.get("loja") or "").strip()
    context.user_data["cadastro_numero_loja"] = (membro.get("Número da loja") or membro.get("numero_loja") or "").strip()
    context.user_data["cadastro_oriente"] = (membro.get("Oriente") or membro.get("oriente") or "").strip()
    context.user_data["cadastro_potencia"] = (membro.get("Potência") or membro.get("potencia") or "").strip()

    await navegar_para(
        update, context,
        "Editar Cadastro",
        "✏️ *Editar cadastro*\n\nVamos passar pelos campos novamente.\nComece enviando seu *nome completo*:",
        _teclado_nav(NOME)
    )
    return NOME


# ============================================
# RECEBIMENTO DE DADOS (TEXTO)
# ============================================

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe e valida o nome."""
    nome = (update.message.text or "").strip()
    if len(nome) < 3:
        await update.message.reply_text("❌ Nome muito curto. Envie seu *nome completo*:", parse_mode="Markdown")
        return NOME

    context.user_data["cadastro_nome"] = nome
    await navegar_para(update, context, "Cadastro", "Envie sua *data de nascimento* (DD/MM/AAAA):", _teclado_nav(DATA_NASC))
    return DATA_NASC


async def receber_data_nasc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe e valida a data de nascimento."""
    texto = (update.message.text or "").strip()
    if not _validar_data_nasc(texto):
        await update.message.reply_text("❌ Data inválida. Envie no formato *DD/MM/AAAA*:", parse_mode="Markdown")
        return DATA_NASC

    context.user_data["cadastro_data_nasc"] = texto
    await navegar_para(update, context, "Cadastro", "Selecione seu *grau*:", _teclado_grau())
    return GRAU


async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o nome da loja."""
    loja = (update.message.text or "").strip()
    if len(loja) < 2:
        await update.message.reply_text("❌ Informe o *nome da sua loja*:", parse_mode="Markdown")
        return LOJA

    context.user_data["cadastro_loja"] = loja
    await navegar_para(
        update, context,
        "Cadastro",
        "Informe o *número da sua loja* (somente números, ou 0):",
        _teclado_nav(NUMERO_LOJA)
    )
    return NUMERO_LOJA


async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o número da loja."""
    numero = (update.message.text or "").strip()
    if not _validar_numero_loja(numero):
        await update.message.reply_text("❌ Número inválido. Envie somente números (ex: 0, 12, 345):")
        return NUMERO_LOJA

    context.user_data["cadastro_numero_loja"] = numero
    await navegar_para(update, context, "Cadastro", "Informe seu *Oriente*:", _teclado_nav(ORIENTE))
    return ORIENTE


async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o oriente."""
    oriente = (update.message.text or "").strip()
    if len(oriente) < 2:
        await update.message.reply_text("❌ Informe seu *Oriente*:", parse_mode="Markdown")
        return ORIENTE

    context.user_data["cadastro_oriente"] = oriente
    await navegar_para(update, context, "Cadastro", "Informe sua *Potência*:", _teclado_nav(POTENCIA))
    return POTENCIA


async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a potência."""
    potencia = (update.message.text or "").strip()
    if len(potencia) < 2:
        await update.message.reply_text("❌ Informe sua *Potência*:", parse_mode="Markdown")
        return POTENCIA

    context.user_data["cadastro_potencia"] = potencia
    await _mostrar_confirmacao(update, context)
    return CONFIRMAR


# ============================================
# SETTERS (BOTÕES)
# ============================================

async def set_grau_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Define o grau selecionado via botão."""
    query = update.callback_query
    await query.answer()

    try:
        _, grau = query.data.split("|", 1)
    except Exception:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "❌ Opção inválida. Selecione seu grau novamente:",
            _teclado_grau()
        )
        return GRAU

    if grau not in GRAUS_OPCOES:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "❌ Opção inválida. Selecione seu grau:",
            _teclado_grau()
        )
        return GRAU

    context.user_data["cadastro_grau"] = grau
    await navegar_para(update, context, "Cadastro", "Você é *Venerável Mestre*?", _teclado_vm())
    return VM


async def set_vm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Define se é Venerável Mestre via botão."""
    query = update.callback_query
    await query.answer()

    try:
        _, vm = query.data.split("|", 1)
    except Exception:
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "❌ Opção inválida. Você é Venerável Mestre?",
            _teclado_vm()
        )
        return VM

    if vm not in (VM_SIM, VM_NAO):
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "❌ Opção inválida. Você é Venerável Mestre?",
            _teclado_vm()
        )
        return VM

    context.user_data["cadastro_vm"] = vm
    await navegar_para(update, context, "Cadastro", "Informe o *nome da sua loja*:", _teclado_nav(LOJA))
    return LOJA


# ============================================
# CONFIRMAÇÃO FINAL
# ============================================

async def _mostrar_confirmacao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe tela de confirmação com resumo dos dados."""
    texto = _resumo_cadastro(context)
    await navegar_para(update, context, "Confirmar Cadastro", texto, _teclado_confirmar())


async def confirmar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma e salva o cadastro."""
    query = update.callback_query
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

        cadastrar_membro(dados_membro)

        # Preserva pos_cadastro
        pos = context.user_data.get("pos_cadastro")
        context.user_data.clear()
        if pos:
            context.user_data["pos_cadastro"] = pos

        # Executa ação pós-cadastro se existir
        if pos and isinstance(pos, dict) and pos.get("acao") == "confirmar":
            try:
                from src.eventos import iniciar_confirmacao_presenca_pos_cadastro
                await iniciar_confirmacao_presenca_pos_cadastro(update, context, pos)
                context.user_data.pop("pos_cadastro", None)
            except Exception as e:
                logger.error(f"Erro no pos_cadastro: {e}\n{traceback.format_exc()}")

        await navegar_para(
            update, context,
            "Cadastro Concluído",
            "✅ *Cadastro realizado com sucesso!*\n\nSeus dados estão registrados sob a proteção do sigilo maçônico.\nUse o menu acima para continuar.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")
            ]])
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Erro em confirmar_cadastro: {e}\n{traceback.format_exc()}")
        await _enviar_ou_editar_mensagem(
            context, update.effective_user.id, TIPO_RESULTADO,
            "❌ Ocorreu um erro ao salvar seus dados. Tente novamente mais tarde."
        )
        return ConversationHandler.END


# ============================================
# NAVEGAÇÃO (VOLTAR / CANCELAR)
# ============================================

async def navegacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa comandos de navegação (voltar/cancelar)."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data == "cancelar":
        return await cancelar_cadastro(update, context)

    if data.startswith("voltar|"):
        try:
            _, estado_str = data.split("|", 1)
            estado = int(estado_str)
        except Exception:
            estado = NOME

        estado = max(NOME, min(CONFIRMAR, estado))
        
        # Reapresenta a pergunta do estado correspondente
        if estado == GRAU:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "Selecione seu *grau*:",
                _teclado_grau()
            )
        elif estado == VM:
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                "Você é *Venerável Mestre*?",
                _teclado_vm()
            )
        else:
            textos = {
                NOME: "Envie seu *nome completo*:",
                DATA_NASC: "Envie sua *data de nascimento* (DD/MM/AAAA):",
                LOJA: "Informe o *nome da sua loja*:",
                NUMERO_LOJA: "Informe o *número da sua loja* (somente números, ou 0):",
                ORIENTE: "Informe seu *Oriente*:",
                POTENCIA: "Informe sua *Potência*:",
            }
            await _enviar_ou_editar_mensagem(
                context, update.effective_user.id, TIPO_RESULTADO,
                textos.get(estado, "Envie a informação:"),
                _teclado_nav(estado)
            )
        return estado

    return NOME


async def cancelar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o processo de cadastro."""
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await navegar_para(
                update, context,
                "Cadastro",
                "Operação cancelada.",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu_principal")
                ]])
            )
        elif update.message:
            await update.message.reply_text("Cadastro cancelado. Você pode iniciar novamente com /start.")
    except Exception as e:
        logger.error(f"Erro em cancelar_cadastro: {e}\n{traceback.format_exc()}")

    # Limpa dados, preservando pos_cadastro
    pos = context.user_data.get("pos_cadastro")
    context.user_data.clear()
    if pos:
        context.user_data["pos_cadastro"] = pos
        
    return ConversationHandler.END


# ============================================
# CONVERSATION HANDLER
# ============================================

cadastro_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(iniciar_cadastro_callback, pattern=r"^iniciar_cadastro$"),
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
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_numero_loja),
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