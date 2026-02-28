# src/cadastro.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from src.sheets import buscar_membro, cadastrar_membro
import logging
import traceback

logger = logging.getLogger(__name__)

# Estados da conversação para o cadastro de membro
NOME, DATA_NASC, GRAU, LOJA, NUMERO_LOJA, ORIENTE, POTENCIA, CONFIRMAR = range(8)

async def cadastro_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o cadastro de membro. Se estiver em grupo, redireciona para privado."""
    logger.info(f"cadastro_start chamado - chat_type: {update.effective_chat.type}, user_id: {update.effective_user.id}")
    
    try:
        if update.effective_chat.type in ["group", "supergroup"]:
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    "🔔 O cadastro será feito no meu chat privado. Verifique suas mensagens."
                )
            else:
                await update.message.reply_text(
                    "🔔 O cadastro será feito no meu chat privado. Verifique suas mensagens."
                )
            # Inicia o cadastro no privado
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="Olá, irmão! Para ter acesso completo às funcionalidades do bot, preciso de algumas informações.\n\n"
                     "Qual o seu *Nome completo*?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
                ]])
            )
            logger.info(f"Primeira pergunta enviada para o privado do usuário {update.effective_user.id}")
            return NOME

        # Já está em privado
        telegram_id = update.effective_user.id
        membro = buscar_membro(telegram_id)

        if membro:
            await update.message.reply_text(
                f"Você já está cadastrado como {membro.get('Nome', '')}. "
                "Seus dados são:\n"
                f"Loja: {membro.get('Loja', '')}\n"
                f"Grau: {membro.get('Grau', '')}\n"
                f"Oriente: {membro.get('Oriente', '')}\n"
                f"Potência: {membro.get('Potência', '')}\n\n"
                "Para editar seu cadastro, use a opção 'Meu cadastro' no menu."
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                "Olá, irmão! Para ter acesso completo às funcionalidades do bot, preciso de algumas informações.\n\n"
                "Qual o seu *Nome completo*?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
                ]])
            )
            logger.info(f"Iniciando cadastro no privado para usuário {telegram_id}")
            return NOME
    except Exception as e:
        logger.error(f"Erro em cadastro_start: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END

async def navegacao_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lida com botões de navegação (voltar, cancelar) durante o cadastro."""
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.info(f"navegacao_callback: data={data}, user={update.effective_user.id}")

    try:
        if data == "cancelar":
            await cancelar_cadastro(update, context)
            return ConversationHandler.END

        if data.startswith("voltar|"):
            estado_destino = int(data.split("|")[1])
            await enviar_pergunta_estado(update, context, estado_destino)
            return estado_destino
    except Exception as e:
        logger.error(f"Erro em navegacao_callback: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END

async def enviar_pergunta_estado(update: Update, context: ContextTypes.DEFAULT_TYPE, estado: int):
    """Envia a pergunta correspondente ao estado, com botões de navegação."""
    logger.info(f"enviar_pergunta_estado: estado={estado}, user={update.effective_user.id}")
    try:
        texto = ""
        botoes = []

        # Botão cancelar sempre presente
        botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])

        # Adiciona botão voltar se não for o primeiro estado
        if estado > NOME:
            botoes.insert(0, [InlineKeyboardButton("⬅️ Voltar", callback_data=f"voltar|{estado-1}")])

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
        elif estado == CONFIRMAR:
            # Resumo será tratado separadamente
            return

        reply_markup = InlineKeyboardMarkup(botoes) if botoes else None

        if update.callback_query:
            await update.callback_query.edit_message_text(
                texto,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=texto,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Erro em enviar_pergunta_estado: {e}\n{traceback.format_exc()}")

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_nome chamado: user={update.effective_user.id}, text={update.message.text}")
    try:
        context.user_data["cadastro_nome"] = update.message.text
        await enviar_pergunta_estado(update, context, DATA_NASC)
        return DATA_NASC
    except Exception as e:
        logger.error(f"Erro em receber_nome: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END

async def receber_data_nasc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_data_nasc chamado: user={update.effective_user.id}, text={update.message.text}")
    try:
        context.user_data["cadastro_data_nasc"] = update.message.text
        await enviar_pergunta_estado(update, context, GRAU)
        return GRAU
    except Exception as e:
        logger.error(f"Erro em receber_data_nasc: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END

async def receber_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_grau chamado: user={update.effective_user.id}, text={update.message.text}")
    try:
        context.user_data["cadastro_grau"] = update.message.text
        await enviar_pergunta_estado(update, context, LOJA)
        return LOJA
    except Exception as e:
        logger.error(f"Erro em receber_grau: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END

async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_loja chamado: user={update.effective_user.id}, text={update.message.text}")
    try:
        context.user_data["cadastro_loja"] = update.message.text
        await enviar_pergunta_estado(update, context, NUMERO_LOJA)
        return NUMERO_LOJA
    except Exception as e:
        logger.error(f"Erro em receber_loja: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END

async def receber_numero_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_numero_loja chamado: user={update.effective_user.id}, text={update.message.text}")
    try:
        context.user_data["cadastro_numero_loja"] = update.message.text
        await enviar_pergunta_estado(update, context, ORIENTE)
        return ORIENTE
    except Exception as e:
        logger.error(f"Erro em receber_numero_loja: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END

async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_oriente chamado: user={update.effective_user.id}, text={update.message.text}")
    try:
        context.user_data["cadastro_oriente"] = update.message.text
        await enviar_pergunta_estado(update, context, POTENCIA)
        return POTENCIA
    except Exception as e:
        logger.error(f"Erro em receber_oriente: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END

async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"receber_potencia chamado: user={update.effective_user.id}, text={update.message.text}")
    try:
        context.user_data["cadastro_potencia"] = update.message.text
        await mostrar_resumo(update, context)
        return CONFIRMAR
    except Exception as e:
        logger.error(f"Erro em receber_potencia: {e}\n{traceback.format_exc()}")
        return ConversationHandler.END

async def mostrar_resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"mostrar_resumo chamado: user={update.effective_user.id}")
    try:
        nome = context.user_data.get("cadastro_nome", "")
        data_nasc = context.user_data.get("cadastro_data_nasc", "")
        grau = context.user_data.get("cadastro_grau", "")
        loja = context.user_data.get("cadastro_loja", "")
        numero = context.user_data.get("cadastro_numero_loja", "")
        oriente = context.user_data.get("cadastro_oriente", "")
        potencia = context.user_data.get("cadastro_potencia", "")

        resumo = (
            f"📋 *Resumo do cadastro*\n\n"
            f"Nome: {nome}\n"
            f"Data nasc.: {data_nasc}\n"
            f"Grau: {grau}\n"
            f"Loja: {loja} {numero}\n"
            f"Oriente: {oriente}\n"
            f"Potência: {potencia}\n\n"
            f"*Tudo correto?*"
        )

        botoes = [
            [InlineKeyboardButton("✅ Confirmar", callback_data="confirmar_cadastro")],
            [InlineKeyboardButton("🔄 Refazer", callback_data="voltar|0")],  # Volta para o início
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")]
        ]

        if update.callback_query:
            await update.callback_query.edit_message_text(
                resumo,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(botoes)
            )
        else:
            await update.message.reply_text(
                resumo,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(botoes)
            )
    except Exception as e:
        logger.error(f"Erro em mostrar_resumo: {e}\n{traceback.format_exc()}")

async def confirmar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Salva os dados na planilha e finaliza."""
    query = update.callback_query
    await query.answer()
    logger.info(f"confirmar_cadastro chamado: user={update.effective_user.id}")

    try:
        dados_membro = {
            "nome": context.user_data["cadastro_nome"],
            "data_nasc": context.user_data["cadastro_data_nasc"],
            "grau": context.user_data["cadastro_grau"],
            "loja": context.user_data["cadastro_loja"],
            "numero_loja": context.user_data["cadastro_numero_loja"],
            "oriente": context.user_data["cadastro_oriente"],
            "potencia": context.user_data["cadastro_potencia"],
            "telegram_id": update.effective_user.id,
            "cargo": "",
        }
        cadastrar_membro(dados_membro)

        # Verifica ação pendente
        if "pos_cadastro" in context.user_data:
            acao = context.user_data["pos_cadastro"]
            if acao.get("acao") == "confirmar":
                from src.eventos import iniciar_confirmacao_presenca_pos_cadastro
                await iniciar_confirmacao_presenca_pos_cadastro(update, context, acao)
                context.user_data.pop("pos_cadastro", None)
                return ConversationHandler.END

        await query.edit_message_text(
            "✅ *Cadastro realizado com sucesso!* Bem-vindo, irmão!\n\n"
            "Use /start para acessar o menu principal.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Erro em confirmar_cadastro: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("❌ Ocorreu um erro ao salvar seus dados. Tente novamente mais tarde.")
        return ConversationHandler.END

async def cancelar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o cadastro e limpa os dados."""
    logger.info(f"cancelar_cadastro chamado: user={update.effective_user.id}")
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                "Cadastro cancelado. Você pode iniciar novamente com /start."
            )
        else:
            await update.message.reply_text("Cadastro cancelado. Você pode iniciar novamente com /start.")
        context.user_data.clear()
    except Exception as e:
        logger.error(f"Erro em cancelar_cadastro: {e}\n{traceback.format_exc()}")
    return ConversationHandler.END

cadastro_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", cadastro_start),
    ],
    states={
        NOME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome),
            CallbackQueryHandler(navegacao_callback, pattern="^(voltar|cancelar)")
        ],
        DATA_NASC: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_data_nasc),
            CallbackQueryHandler(navegacao_callback, pattern="^(voltar|cancelar)")
        ],
        GRAU: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_grau),
            CallbackQueryHandler(navegacao_callback, pattern="^(voltar|cancelar)")
        ],
        LOJA: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_loja),
            CallbackQueryHandler(navegacao_callback, pattern="^(voltar|cancelar)")
        ],
        NUMERO_LOJA: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_numero_loja),
            CallbackQueryHandler(navegacao_callback, pattern="^(voltar|cancelar)")
        ],
        ORIENTE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_oriente),
            CallbackQueryHandler(navegacao_callback, pattern="^(voltar|cancelar)")
        ],
        POTENCIA: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receber_potencia),
            CallbackQueryHandler(navegacao_callback, pattern="^(voltar|cancelar)")
        ],
        CONFIRMAR: [
            CallbackQueryHandler(confirmar_cadastro, pattern="^confirmar_cadastro$"),
            CallbackQueryHandler(navegacao_callback, pattern="^(voltar|cancelar)")
        ],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_cadastro)],
)