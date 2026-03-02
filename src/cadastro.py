# src/cadastro.py

import os
import logging
import traceback
from datetime import datetime, timedelta
from typing import Optional, Set, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)

from src.sheets import buscar_membro, cadastrar_membro

logger = logging.getLogger(__name__)

# Estados
NOME, DATA_NASC, GRAU, LOJA, NUMERO_LOJA, ORIENTE, POTENCIA, CONFIRMAR = range(8)

# Env
GRUPO_PRINCIPAL_ID = os.getenv("GRUPO_PRINCIPAL_ID")  # ex "-1003721338228"
BOT_USERNAME = os.getenv("BOT_USERNAME")  # ex "MeuBot" (sem @)

# Admin fixo (pode ser "123" ou "123,456")
def _parse_admin_ids(value: Optional[str]) -> Set[int]:
    if not value:
        return set()
    parts = value.replace(",", " ").split()
    ids: Set[int] = set()
    for p in parts:
        try:
            ids.add(int(p.strip()))
        except ValueError:
            pass
    return ids


ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_TELEGRAM_ID"))

# Expiração do cadastro interrompido
TEMPO_MAXIMO_CADASTRO = timedelta(hours=int(os.getenv("TEMPO_MAXIMO_CADASTRO_HORAS", "24")))


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _agora() -> datetime:
    return datetime.now()


def _cadastro_expirou(user_data: dict) -> bool:
    inicio = user_data.get("cadastro_inicio")
    if not inicio:
        return False
    try:
        dt = datetime.fromisoformat(inicio)
    except Exception:
        return False
    return (_agora() - dt) > TEMPO_MAXIMO_CADASTRO


def _preservar_e_limpar_user_data(context: ContextTypes.DEFAULT_TYPE, preservar: Optional[Set[str]] = None):
    preservar = preservar or set()
    backup = {k: context.user_data.get(k) for k in preservar if k in context.user_data}
    context.user_data.clear()
    context.user_data.update(backup)


async def verificar_membro_no_grupo(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Retorna True se for membro do grupo principal.
    Se GRUPO_PRINCIPAL_ID não estiver configurado, não bloqueia (True).
    """
    if not GRUPO_PRINCIPAL_ID:
        return True

    try:
        cm = await context.bot.get_chat_member(chat_id=int(GRUPO_PRINCIPAL_ID), user_id=user_id)
        return cm.status not in ("left", "kicked")
    except Exception as e:
        # Se falhar API, não bloqueia (pra não matar o bot)
        logger.warning(f"Falha ao verificar membro no grupo: user={user_id} erro={e}")
        return True


def _teclado_inicio(mostrar_continuar: bool) -> InlineKeyboardMarkup:
    linhas = [[InlineKeyboardButton("📝 INICIAR CADASTRO", callback_data="iniciar_cadastro")]]
    if mostrar_continuar:
        linhas.append([InlineKeyboardButton("⏩ CONTINUAR CADASTRO", callback_data="continuar_cadastro")])
    linhas.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(linhas)


def _teclado_nav(estado_atual: int) -> InlineKeyboardMarkup:
    voltar_map = {
        NOME: NOME,
        DATA_NASC: NOME,
        GRAU: DATA_NASC,
        LOJA: GRAU,
        NUMERO_LOJA: LOJA,
        ORIENTE: NUMERO_LOJA,
        POTENCIA: ORIENTE,
        CONFIRMAR: POTENCIA,
    }
    alvo = voltar_map.get(estado_atual, NOME)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{alvo}"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancelar"),
            ]
        ]
    )


def _teclado_confirmar() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirmar", callback_data="confirmar_cadastro")],
            [InlineKeyboardButton("🔄 Refazer", callback_data=f"voltar|{NOME}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
    )


def _deep_link_private() -> Optional[str]:
    if not BOT_USERNAME:
        return None
    # deep link simples (sem parâmetros)
    return f"https://t.me/{BOT_USERNAME}?start=1"


async def _enviar_menu_principal(user_id: int, context: ContextTypes.DEFAULT_TYPE, nivel: str, texto: str):
    from src.bot import menu_principal_teclado  # import local para evitar circular

    await context.bot.send_message(
        chat_id=user_id,
        text=texto,
        parse_mode="Markdown",
        reply_markup=menu_principal_teclado(nivel),
    )


async def cadastro_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entry point do /start (e também pode ser chamado do grupo via "bode").
    - No grupo: tenta DM; se não conseguir, manda botão "Abrir privado".
    - No privado: se cadastrado -> menu; senão -> oferece iniciar/continuar cadastro.
    """
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    admin = _is_admin(user_id)

    logger.info(f"cadastro_start: chat_type={chat_type} user_id={user_id} admin={admin}")

    try:
        # 1) Se for grupo: ponte pro privado
        if chat_type in ("group", "supergroup"):
            membro_ok = await verificar_membro_no_grupo(user_id, context)
            if not membro_ok and not admin:
                # aqui é o único caso que eu respondo no grupo, pra deixar claro o bloqueio
                if update.message:
                    await update.message.reply_text(
                        "⛔ Acesso não permitido. Você precisa ser membro do grupo principal para usar este bot."
                    )
                return ConversationHandler.END

            # tenta DM
            try:
                membro = buscar_membro(user_id)
                if admin:
                    await _enviar_menu_principal(user_id, context, "3", "👑 *Administrador*")
                elif membro:
                    nivel = str(membro.get("Nivel", "1"))
                    nome = membro.get("Nome", "irmão")
                    await _enviar_menu_principal(
                        user_id, context, nivel, f"Bem-vindo de volta, irmão *{nome}*!"
                    )
                else:
                    # oferece iniciar/continuar no privado
                    mostrar_continuar = bool(context.user_data.get("cadastro_em_andamento")) and not _cadastro_expirou(context.user_data)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="👋 *Bem-vindo ao Bode Andarilho!*\n\nPara continuar, toque em um botão abaixo:",
                        parse_mode="Markdown",
                        reply_markup=_teclado_inicio(mostrar_continuar),
                    )
            except Exception as e:
                # Não conseguiu mandar DM -> manda botão no grupo
                link = _deep_link_private()
                if link and update.message:
                    await update.message.reply_text(
                        "🔔 Para continuar, abra meu chat privado:",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton("📩 Abrir privado", url=link)]]
                        ),
                    )
                elif update.message:
                    await update.message.reply_text("🔔 Para continuar, abra meu privado e envie /start.")
                logger.warning(f"Não consegui DM user={user_id}: {e}")

            return ConversationHandler.END

        # 2) Privado: decide menu vs cadastro
        membro = buscar_membro(user_id)

        if admin:
            await _enviar_menu_principal(user_id, context, "3", "👑 *Administrador*")
            return ConversationHandler.END

        if membro:
            nivel = str(membro.get("Nivel", "1"))
            nome = membro.get("Nome", "irmão")
            await _enviar_menu_principal(
                user_id, context, nivel, f"Bem-vindo de volta, irmão *{nome}*!"
            )
            return ConversationHandler.END

        # não cadastrado -> oferece iniciar/continuar
        if _cadastro_expirou(context.user_data):
            # se expirou, reseta o andamento mas preserva pos_cadastro
            _preservar_e_limpar_user_data(context, preservar={"pos_cadastro"})

        mostrar_continuar = bool(context.user_data.get("cadastro_em_andamento"))
        if update.message:
            await update.message.reply_text(
                "📝 Você ainda não possui cadastro.\n\nToque em um botão abaixo:",
                reply_markup=_teclado_inicio(mostrar_continuar),
            )
        else:
            # raríssimo: /start vindo de callback, mas ok
            await context.bot.send_message(
                chat_id=user_id,
                text="📝 Você ainda não possui cadastro.\n\nToque em um botão abaixo:",
                reply_markup=_teclado_inicio(mostrar_continuar),
            )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Erro em cadastro_start: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END


async def iniciar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # preserva ação pendente pós-cadastro
    pos = context.user_data.get("pos_cadastro")
    _preservar_e_limpar_user_data(context, preservar={"pos_cadastro"})

    if pos:
        context.user_data["pos_cadastro"] = pos

    context.user_data["cadastro_em_andamento"] = True
    context.user_data["cadastro_inicio"] = _agora().isoformat()
    context.user_data["estado_atual"] = NOME

    await query.edit_message_text(
        "Envie seu *nome completo*:",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(NOME),
    )
    return NOME


async def continuar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if _cadastro_expirou(context.user_data):
        _preservar_e_limpar_user_data(context, preservar={"pos_cadastro"})
        await query.edit_message_text("Seu cadastro expirou. Envie /start e inicie novamente.")
        return ConversationHandler.END

    estado = context.user_data.get("estado_atual", NOME)
    textos = {
        NOME: "Envie seu *nome completo*:",
        DATA_NASC: "Envie sua *data de nascimento* (DD/MM/AAAA):",
        GRAU: "Qual o seu *grau*?",
        LOJA: "Informe o *nome da sua loja*:",
        NUMERO_LOJA: "Informe o *número da loja* (somente números, ou 0):",
        ORIENTE: "Informe seu *Oriente*:",
        POTENCIA: "Informe sua *Potência*:",
    }

    await query.edit_message_text(
        textos.get(estado, "Envie a informação:"),
        parse_mode="Markdown",
        reply_markup=_teclado_nav(estado),
    )
    return estado


async def navegacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data == "cancelar":
        return await cancelar_cadastro(update, context)

    if data.startswith("voltar|"):
        try:
            estado = int(data.split("|", 1)[1])
        except Exception:
            estado = NOME

        context.user_data["estado_atual"] = estado

        textos = {
            NOME: "Envie seu *nome completo*:",
            DATA_NASC: "Envie sua *data de nascimento* (DD/MM/AAAA):",
            GRAU: "Qual o seu *grau*?",
            LOJA: "Informe o *nome da sua loja*:",
            NUMERO_LOJA: "Informe o *número da loja* (somente números, ou 0):",
            ORIENTE: "Informe seu *Oriente*:",
            POTENCIA: "Informe sua *Potência*:",
        }

        await query.edit_message_text(
            textos.get(estado, "Envie a informação:"),
            parse_mode="Markdown",
            reply_markup=_teclado_nav(estado),
        )
        return estado

    return ConversationHandler.END


async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_nome"] = update.message.text.strip()
    context.user_data["estado_atual"] = DATA_NASC
    await update.message.reply_text(
        "Envie sua *data de nascimento* (DD/MM/AAAA):",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(DATA_NASC),
    )
    return DATA_NASC


async def receber_data_nasc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_data_nasc"] = update.message.text.strip()
    context.user_data["estado_atual"] = GRAU
    await update.message.reply_text(
        "Qual o seu *grau*?",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(GRAU),
    )
    return GRAU


async def receber_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_grau"] = update.message.text.strip()
    context.user_data["estado_atual"] = LOJA
    await update.message.reply_text(
        "Informe o *nome da sua loja*:",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(LOJA),
    )
    return LOJA


async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_loja"] = update.message.text.strip()
    context.user_data["estado_atual"] = NUMERO_LOJA
    await update.message.reply_text(
        "Informe o *número da loja* (somente números, ou 0):",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(NUMERO_LOJA),
    )
    return NUMERO_LOJA


async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_numero_loja"] = update.message.text.strip()
    context.user_data["estado_atual"] = ORIENTE
    await update.message.reply_text(
        "Informe seu *Oriente*:",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(ORIENTE),
    )
    return ORIENTE


async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_oriente"] = update.message.text.strip()
    context.user_data["estado_atual"] = POTENCIA
    await update.message.reply_text(
        "Informe sua *Potência*:",
        parse_mode="Markdown",
        reply_markup=_teclado_nav(POTENCIA),
    )
    return POTENCIA


async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_potencia"] = update.message.text.strip()
    context.user_data["estado_atual"] = CONFIRMAR
    await mostrar_resumo(update, context)
    return CONFIRMAR


async def mostrar_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = context.user_data.get("cadastro_nome", "")
    data_nasc = context.user_data.get("cadastro_data_nasc", "")
    grau = context.user_data.get("cadastro_grau", "")
    loja = context.user_data.get("cadastro_loja", "")
    numero = context.user_data.get("cadastro_numero_loja", "")
    oriente = context.user_data.get("cadastro_oriente", "")
    potencia = context.user_data.get("cadastro_potencia", "")

    resumo = (
        "📋 *Resumo do cadastro*\n\n"
        f"Nome: {nome}\n"
        f"Data nasc.: {data_nasc}\n"
        f"Grau: {grau}\n"
        f"Loja: {loja} {numero}\n"
        f"Oriente: {oriente}\n"
        f"Potência: {potencia}\n\n"
        "*Tudo correto?*"
    )

    await update.message.reply_text(resumo, parse_mode="Markdown", reply_markup=_teclado_confirmar())


async def confirmar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        dados_membro: dict[str, Any] = {
            "nome": context.user_data.get("cadastro_nome", ""),
            "data_nasc": context.user_data.get("cadastro_data_nasc", ""),
            "grau": context.user_data.get("cadastro_grau", ""),
            "loja": context.user_data.get("cadastro_loja", ""),
            "numero_loja": context.user_data.get("cadastro_numero_loja", ""),
            "oriente": context.user_data.get("cadastro_oriente", ""),
            "potencia": context.user_data.get("cadastro_potencia", ""),
            "telegram_id": update.effective_user.id,
            "cargo": "",
        }

        # tenta salvar tolerando assinaturas diferentes
        try:
            cadastrar_membro(dados_membro)
        except TypeError:
            try:
                cadastrar_membro(update.effective_user.id, dados_membro)
            except TypeError:
                cadastrar_membro(
                    update.effective_user.id,
                    dados_membro["nome"],
                    dados_membro["data_nasc"],
                    dados_membro["grau"],
                    dados_membro["loja"],
                    dados_membro["numero_loja"],
                    dados_membro["oriente"],
                    dados_membro["potencia"],
                )

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
            "✅ *Cadastro realizado com sucesso!* Bem-vindo, irmão!\n\nUse /start para acessar o menu principal.",
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


# Correção dos padrões dos callbacks - removendo os códigos estranhos
cadastro_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", cadastro_start),
        CallbackQueryHandler(iniciar_cadastro_callback, pattern="^iniciar_cadastro$"),
        CallbackQueryHandler(continuar_cadastro_callback, pattern="^continuar_cadastro$"),
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
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_grau),
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
            CallbackQueryHandler(confirmar_cadastro, pattern="^confirmar_cadastro$"),
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