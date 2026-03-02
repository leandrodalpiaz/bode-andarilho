# src/cadastro.py

import os
import logging
import traceback
from datetime import datetime, timedelta
from typing import Optional, Set

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.sheets import buscar_membro, cadastrar_membro


logger = logging.getLogger(__name__)

# -----------------------------
# Config / Estados
# -----------------------------

NOME, DATA_NASC, GRAU, LOJA, NUMERO_LOJA, ORIENTE, POTENCIA, CONFIRMAR = range(8)

TEMPO_MAXIMO_CADASTRO = timedelta(
    minutes=int(os.getenv("TEMPO_MAXIMO_CADASTRO_MIN", "30"))
)

GRUPO_PRINCIPAL_ID = os.getenv("GRUPO_PRINCIPAL_ID")  # ex: "-1001234567890"


def _parse_admin_ids(env_value: Optional[str]) -> Set[int]:
    """
    ADMIN_TELEGRAM_ID pode ser:
      - "123"
      - "123,456"
      - "123 456"
    """
    if not env_value:
        return set()
    parts = env_value.replace(",", " ").split()
    out: Set[int] = set()
    for p in parts:
        try:
            out.add(int(p.strip()))
        except ValueError:
            pass
    return out


ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_TELEGRAM_ID"))


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _now() -> datetime:
    return datetime.now()


async def verificar_membro_no_grupo(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Confere se o usuário é membro do grupo principal.
    Se GRUPO_PRINCIPAL_ID não estiver configurado, não bloqueia (retorna True).
    """
    if not GRUPO_PRINCIPAL_ID:
        return True

    try:
        chat_id = int(GRUPO_PRINCIPAL_ID)
        cm = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return cm.status not in ("left", "kicked")
    except Exception as e:
        # Falha de API não deve travar o bot inteiro.
        logger.warning(f"Falha ao verificar membro no grupo: user_id={user_id} erro={e}")
        return True


async def _enviar_menu_principal(
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str,
    nivel: str,
):
    """
    Import local para evitar import circular src.bot <-> src.cadastro.
    """
    from src.bot import menu_principal_teclado

    await context.bot.send_message(
        chat_id=user_id,
        text=texto,
        parse_mode="Markdown",
        reply_markup=menu_principal_teclado(nivel),
    )


def _teclado_inicio_cadastro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 INICIAR CADASTRO", callback_data="iniciar_cadastro")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
    )


def _teclado_continuar_cadastro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("▶️ Continuar cadastro", callback_data="continuar_cadastro")],
            [InlineKeyboardButton("🔄 Recomeçar", callback_data="iniciar_cadastro")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
    )


def _teclado_navegacao(estado: int) -> InlineKeyboardMarkup:
    botoes = []
    if estado > NOME:
        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{estado - 1}")])
    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(botoes)


def _cadastro_expirou(context: ContextTypes.DEFAULT_TYPE) -> bool:
    inicio = context.user_data.get("cadastro_inicio")
    if not isinstance(inicio, datetime):
        return True
    return (_now() - inicio) > TEMPO_MAXIMO_CADASTRO


def _preservar_e_limpar_user_data(context: ContextTypes.DEFAULT_TYPE, preservar_chaves: Optional[Set[str]] = None):
    """
    Limpa user_data preservando algumas chaves (ex.: pos_cadastro).
    """
    if preservar_chaves is None:
        preservar_chaves = set()

    snapshot = {k: context.user_data.get(k) for k in preservar_chaves if k in context.user_data}
    context.user_data.clear()
    context.user_data.update(snapshot)


# -----------------------------
# Entry point / Ponte grupo->privado
# -----------------------------

async def cadastro_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fluxo:
    - Grupo: NÃO conversa no grupo; tenta falar no privado:
        - Se admin: manda menu admin no privado
        - Se cadastrado: manda menu no privado
        - Se não cadastrado: manda botão "Iniciar cadastro" no privado
      (Sem mensagem no grupo para membros)
    - Privado:
        - Se admin/cadastrado: menu
        - Se não cadastrado: botão iniciar (ou continuar se houver andamento)
    """
    try:
        user_id = update.effective_user.id
        chat_type = update.effective_chat.type if update.effective_chat else None

        logger.info(f"cadastro_start: chat_type={chat_type} user_id={user_id}")

        admin = _is_admin(user_id)

        # 1) GRUPO/SUPERGRUPO: ponte
        if chat_type in ("group", "supergroup"):
            is_member = await verificar_membro_no_grupo(user_id, context)
            if not is_member and not admin:
                # Aqui pode responder no grupo, pois é caso de bloqueio.
                msg = (
                    "⛔ *Acesso não permitido*\n\n"
                    "Você precisa ser membro do grupo para usar este bot."
                )
                if update.callback_query:
                    await update.callback_query.answer()
                    await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
                elif update.message:
                    await update.message.reply_text(msg, parse_mode="Markdown")
                return ConversationHandler.END

            membro = buscar_membro(user_id)

            # Sem mensagem no grupo para membros: só DM
            try:
                if admin:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="👑 *Administrador*\n\nUse o menu abaixo para navegar.",
                        parse_mode="Markdown",
                    )
                    await _enviar_menu_principal(user_id, context, "👑 *Administrador*", "3")
                    return ConversationHandler.END

                if membro:
                    nivel = str(membro.get("Nivel", "1"))
                    nome = membro.get("Nome", "irmão")
                    await _enviar_menu_principal(
                        user_id,
                        context,
                        f"Bem-vindo de volta, irmão {nome}!\n\nO que deseja fazer?",
                        nivel,
                    )
                    return ConversationHandler.END

                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "👋 Olá, irmão! Para começar a usar o Bode Andarilho, "
                        "preciso fazer seu cadastro.\n\n"
                        "Clique no botão abaixo quando estiver pronto:"
                    ),
                    reply_markup=_teclado_inicio_cadastro(),
                )
            except Exception as e:
                logger.warning(f"Não consegui enviar DM para user_id={user_id}: {e}")

            return ConversationHandler.END

        # 2) PRIVADO: conversa
        if chat_type == "private":
            membro = buscar_membro(user_id)

            # Admin sempre tem acesso ao menu, mesmo sem cadastro
            if admin:
                if membro:
                    nivel = str(membro.get("Nivel", "3"))
                    nome = membro.get("Nome", "Administrador")
                    await _enviar_menu_principal(
                        user_id,
                        context,
                        f"Bem-vindo de volta, irmão {nome}!\n\nO que deseja fazer?",
                        nivel,
                    )
                else:
                    await _enviar_menu_principal(
                        user_id,
                        context,
                        "👑 *Bem-vindo, Administrador!*\n\nVocê tem acesso total ao sistema.",
                        "3",
                    )
                return ConversationHandler.END

            # Usuário cadastrado: menu e fim
            if membro:
                nivel = str(membro.get("Nivel", "1"))
                nome = membro.get("Nome", "irmão")
                await _enviar_menu_principal(
                    user_id,
                    context,
                    f"Bem-vindo de volta, irmão {nome}!\n\nO que deseja fazer?",
                    nivel,
                )
                return ConversationHandler.END

            # Não cadastrado: oferecer continuar/recomeçar se há andamento e não expirou
            if context.user_data.get("cadastro_em_andamento"):
                if _cadastro_expirou(context):
                    logger.info(f"Cadastro expirado: limpando user_data user_id={user_id}")
                    _preservar_e_limpar_user_data(context, preservar_chaves={"pos_cadastro"})
                else:
                    if update.message:
                        await update.message.reply_text(
                            "Você já tem um cadastro em andamento. Deseja continuar de onde parou ou recomeçar?",
                            reply_markup=_teclado_continuar_cadastro(),
                        )
                    else:
                        # fallback (caso raro)
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="Você já tem um cadastro em andamento. Deseja continuar ou recomeçar?",
                            reply_markup=_teclado_continuar_cadastro(),
                        )
                    return ConversationHandler.END

            # Primeiro contato no privado: botão iniciar
            if update.message:
                await update.message.reply_text(
                    "👋 Olá, irmão! Para começar a usar o Bode Andarilho, preciso fazer seu cadastro.\n\n"
                    "Clique no botão abaixo quando estiver pronto:",
                    reply_markup=_teclado_inicio_cadastro(),
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="👋 Olá, irmão! Para começar a usar o Bode Andarilho, preciso fazer seu cadastro.\n\n"
                         "Clique no botão abaixo quando estiver pronto:",
                    reply_markup=_teclado_inicio_cadastro(),
                )

            return ConversationHandler.END

        # 3) Outros tipos (canal etc.)
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Erro em cadastro_start: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END


# -----------------------------
# Callbacks de início/continuidade
# -----------------------------

async def iniciar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Começa efetivamente o cadastro no privado."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    logger.info(f"iniciar_cadastro_callback: user_id={user_id}")

    # Preserva ações pendentes (ex.: confirmação pós-cadastro)
    _preservar_e_limpar_user_data(context, preservar_chaves={"pos_cadastro"})

    context.user_data["cadastro_em_andamento"] = True
    context.user_data["cadastro_inicio"] = _now()
    context.user_data["ultimo_estado"] = NOME

    await query.edit_message_text(
        "📝 *Vamos começar!*\n\nQual o seu *Nome completo*?",
        parse_mode="Markdown",
        reply_markup=_teclado_navegacao(NOME),
    )
    return NOME


async def continuar_cadastro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Continua do último estado salvo, se não estiver expirado."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    logger.info(f"continuar_cadastro_callback: user_id={user_id}")

    if not context.user_data.get("cadastro_em_andamento") or _cadastro_expirou(context):
        await query.edit_message_text(
            "Seu cadastro anterior não está mais disponível. Vamos iniciar um novo.",
            reply_markup=_teclado_inicio_cadastro(),
        )
        return ConversationHandler.END

    ultimo_estado = context.user_data.get("ultimo_estado", NOME)
    await enviar_pergunta_estado(update, context, ultimo_estado, edit=True)
    return ultimo_estado


async def navegacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botões de navegação durante cadastro: voltar|N e cancelar."""
    query = update.callback_query
    await query.answer()
    data = query.data

    logger.info(f"navegacao_callback: data={data} user_id={update.effective_user.id}")

    try:
        if data == "cancelar":
            return await cancelar_cadastro(update, context)

        if data.startswith("voltar|"):
            try:
                estado_destino = int(data.split("|", 1)[1])
            except ValueError:
                estado_destino = NOME

            await enviar_pergunta_estado(update, context, estado_destino, edit=True)
            return estado_destino

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Erro em navegacao_callback: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END


# -----------------------------
# Perguntas por estado
# -----------------------------

async def enviar_pergunta_estado(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    estado: int,
    edit: bool = False,
):
    """Envia a pergunta correspondente ao estado, com botões de navegação."""
    user_id = update.effective_user.id
    logger.info(f"enviar_pergunta_estado: estado={estado} user_id={user_id}")

    context.user_data["ultimo_estado"] = estado

    try:
        if estado == CONFIRMAR:
            await mostrar_resumo(update, context)
            return

        if estado == NOME:
            texto = "Qual o seu *Nome completo*?"
        elif estado == DATA_NASC:
            texto = "Qual a sua *Data de nascimento*? (ex: 25/12/1980)"
        elif estado == GRAU:
            texto = "Qual o seu *Grau*?"
        elif estado == LOJA:
            texto = "Qual o *nome da sua Loja*? (apenas o nome, sem número)"
        elif estado == NUMERO_LOJA:
            texto = "Qual o *número da sua Loja*?"
        elif estado == ORIENTE:
            texto = "Qual o *Oriente da sua Loja*?"
        elif estado == POTENCIA:
            texto = "Qual a sua *Potência*?"
        else:
            texto = "Vamos voltar ao início. Qual o seu *Nome completo*?"
            estado = NOME
            context.user_data["ultimo_estado"] = NOME

        markup = _teclado_navegacao(estado)

        if edit and update.callback_query:
            await update.callback_query.edit_message_text(
                texto,
                parse_mode="Markdown",
                reply_markup=markup,
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=texto,
                parse_mode="Markdown",
                reply_markup=markup,
            )

    except Exception as e:
        logger.error(f"Erro em enviar_pergunta_estado: {e}\n{traceback.format_exc()}")


# -----------------------------
# Recebimento de dados
# -----------------------------

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_nome: user_id={update.effective_user.id} text={update.message.text}")
    context.user_data["cadastro_nome"] = update.message.text.strip()
    await enviar_pergunta_estado(update, context, DATA_NASC)
    return DATA_NASC


async def receber_data_nasc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_data_nasc: user_id={update.effective_user.id} text={update.message.text}")
    context.user_data["cadastro_data_nasc"] = update.message.text.strip()
    await enviar_pergunta_estado(update, context, GRAU)
    return GRAU


async def receber_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_grau: user_id={update.effective_user.id} text={update.message.text}")
    context.user_data["cadastro_grau"] = update.message.text.strip()
    await enviar_pergunta_estado(update, context, LOJA)
    return LOJA


async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_loja: user_id={update.effective_user.id} text={update.message.text}")
    context.user_data["cadastro_loja"] = update.message.text.strip()
    await enviar_pergunta_estado(update, context, NUMERO_LOJA)
    return NUMERO_LOJA


async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_numero_loja: user_id={update.effective_user.id} text={update.message.text}")
    context.user_data["cadastro_numero_loja"] = update.message.text.strip()
    await enviar_pergunta_estado(update, context, ORIENTE)
    return ORIENTE


async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_oriente: user_id={update.effective_user.id} text={update.message.text}")
    context.user_data["cadastro_oriente"] = update.message.text.strip()
    await enviar_pergunta_estado(update, context, POTENCIA)
    return POTENCIA


async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_potencia: user_id={update.effective_user.id} text={update.message.text}")
    context.user_data["cadastro_potencia"] = update.message.text.strip()
    await mostrar_resumo(update, context)
    return CONFIRMAR


# -----------------------------
# Resumo / Confirmação
# -----------------------------

async def mostrar_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"mostrar_resumo: user_id={update.effective_user.id}")

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

    botoes = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirmar", callback_data="confirmar_cadastro")],
            [InlineKeyboardButton("🔄 Refazer", callback_data=f"voltar|{NOME}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(resumo, parse_mode="Markdown", reply_markup=botoes)
    else:
        await update.message.reply_text(resumo, parse_mode="Markdown", reply_markup=botoes)


async def confirmar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Salva os dados na planilha e finaliza."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    logger.info(f"confirmar_cadastro: user_id={user_id}")

    try:
        dados_membro = {
            "nome": context.user_data.get("cadastro_nome", ""),
            "data_nasc": context.user_data.get("cadastro_data_nasc", ""),
            "grau": context.user_data.get("cadastro_grau", ""),
            "loja": context.user_data.get("cadastro_loja", ""),
            "numero_loja": context.user_data.get("cadastro_numero_loja", ""),
            "oriente": context.user_data.get("cadastro_oriente", ""),
            "potencia": context.user_data.get("cadastro_potencia", ""),
            "telegram_id": user_id,
            "cargo": "",
        }

        # Tenta salvar (tolerante a assinaturas diferentes)
        try:
            cadastrar_membro(dados_membro)
        except TypeError:
            # fallback se a função espera (telegram_id, dict)
            try:
                cadastrar_membro(user_id, dados_membro)
            except TypeError:
                # fallback se espera parâmetros soltos
                cadastrar_membro(
                    user_id,
                    dados_membro["nome"],
                    dados_membro["data_nasc"],
                    dados_membro["grau"],
                    dados_membro["loja"],
                    dados_membro["numero_loja"],
                    dados_membro["oriente"],
                    dados_membro["potencia"],
                )

        # Remove flags do andamento, mas preserva pos_cadastro se existir
        pos_cadastro = context.user_data.get("pos_cadastro")
        _preservar_e_limpar_user_data(context, preservar_chaves={"pos_cadastro"})

        # Se havia ação pendente pós-cadastro, executa
        if pos_cadastro:
            try:
                acao = pos_cadastro
                if isinstance(acao, dict) and acao.get("acao") == "confirmar":
                    from src.eventos import iniciar_confirmacao_presenca_pos_cadastro
                    await iniciar_confirmacao_presenca_pos_cadastro(update, context, acao)
                    context.user_data.pop("pos_cadastro", None)
                    return ConversationHandler.END
            except Exception as e:
                logger.error(f"Erro em pos_cadastro: {e}\n{traceback.format_exc()}")

        await query.edit_message_text(
            "✅ *Cadastro realizado com sucesso!* Bem-vindo, irmão!\n\nUse /start para acessar o menu principal.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Erro em confirmar_cadastro: {e}\n{traceback.format_exc()}")
        await query.edit_message_text(
            "❌ Ocorreu um erro ao salvar seus dados. Tente novamente mais tarde."
        )
        return ConversationHandler.END


async def cancelar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o cadastro e limpa os dados."""
    logger.info(f"cancelar_cadastro: user_id={update.effective_user.id}")

    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                "Cadastro cancelado. Você pode iniciar novamente com /start."
            )
        elif update.message:
            await update.message.reply_text(
                "Cadastro cancelado. Você pode iniciar novamente com /start."
            )
        _preservar_e_limpar_user_data(context, preservar_chaves={"pos_cadastro"})
    except Exception as e:
        logger.error(f"Erro em cancelar_cadastro: {e}\n{traceback.format_exc()}")

    return ConversationHandler.END


# -----------------------------
# ConversationHandler
# -----------------------------

cadastro_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", cadastro_start),
        CallbackQueryHandler(iniciar_cadastro_callback, pattern="^iniciar_cadastroINNERCHAT_CB_1cyz8kshlquot;),
        CallbackQueryHandler(continuar_cadastro_callback, pattern="^continuar_cadastroINNERCHAT_CB_1cyz8kshlquot;),
    ],
    states={
        NOME: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_nome),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(cancelar|voltar\|\d+)INNERCHAT_CB_1cyz8kshlquot;),
        ],
        DATA_NASC: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_data_nasc),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(cancelar|voltar\|\d+)INNERCHAT_CB_1cyz8kshlquot;),
        ],
        GRAU: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_grau),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(cancelar|voltar\|\d+)INNERCHAT_CB_1cyz8kshlquot;),
        ],
        LOJA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_loja),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(cancelar|voltar\|\d+)INNERCHAT_CB_1cyz8kshlquot;),
        ],
        NUMERO_LOJA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_numero_loja),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(cancelar|voltar\|\d+)INNERCHAT_CB_1cyz8kshlquot;),
        ],
        ORIENTE: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_oriente),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(cancelar|voltar\|\d+)INNERCHAT_CB_1cyz8kshlquot;),
        ],
        POTENCIA: [
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receber_potencia),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(cancelar|voltar\|\d+)INNERCHAT_CB_1cyz8kshlquot;),
        ],
        CONFIRMAR: [
            CallbackQueryHandler(confirmar_cadastro, pattern="^confirmar_cadastroINNERCHAT_CB_1cyz8kshlquot;),
            CallbackQueryHandler(navegacao_callback, pattern=r"^(cancelar|voltar\|\d+)INNERCHAT_CB_1cyz8kshlquot;),
        ],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar_cadastro),
        CallbackQueryHandler(navegacao_callback, pattern=r"^(cancelar|voltar\|\d+)INNERCHAT_CB_1cyz8kshlquot;),
    ],
    allow_reentry=True,
    name="cadastro_handler",
    persistent=False,
)