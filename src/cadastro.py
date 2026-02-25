# src/cadastro.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from src.sheets import buscar_membro, cadastrar_membro

# Estados da conversação para o cadastro de membro
NOME, LOJA, GRAU, ORIENTE, POTENCIA, TELEFONE, FINALIZAR = range(7)

async def cadastro_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o cadastro de membro. Se estiver em grupo, redireciona para privado."""
    
    # Se a interação veio de um grupo, redireciona para privado
    if update.effective_chat.type in ["group", "supergroup"]:
        # Se for callback_query (botão)
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                "🔔 O cadastro deve ser feito no meu chat privado.\n\n"
                "Por favor, clique no meu nome e envie /start no privado para começar."
            )
        # Se for mensagem de texto
        else:
            await update.message.reply_text(
                "🔔 O cadastro deve ser feito no meu chat privado.\n\n"
                "Por favor, clique no meu nome e envie /start no privado para começar."
            )
        return ConversationHandler.END

    # Se já está em privado, prossegue com o cadastro
    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if membro:
        await update.message.reply_text(
            f"Você já está cadastrado como {membro.get('Nome', '')}. "
            "Seus dados são:\n"
            f"Loja: {membro.get('Loja', '')}\n"
            f"Grau: {membro.get('Grau', '')}\n"
            f"Oriente: {membro.get('Oriente', '')}\n"
            f"Potência: {membro.get('Potência', '')}\n"
            f"Telefone: {membro.get('Telefone', '')}\n\n"
            "Para editar seu cadastro, use a opção 'Meu cadastro' no menu."
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "Olá, irmão! Para ter acesso completo às funcionalidades do bot, preciso de algumas informações.\n\n"
            "Qual o seu *Nome completo*?",
            parse_mode="Markdown"
        )
        return NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_nome"] = update.message.text
    await update.message.reply_text("Qual o nome da sua *Loja*?", parse_mode="Markdown")
    return LOJA

async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_loja"] = update.message.text
    await update.message.reply_text("Qual o seu *Grau*?", parse_mode="Markdown")
    return GRAU

async def receber_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_grau"] = update.message.text
    await update.message.reply_text("Qual o seu *Oriente*?", parse_mode="Markdown")
    return ORIENTE

async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_oriente"] = update.message.text
    await update.message.reply_text("Qual a sua *Potência*?", parse_mode="Markdown")
    return POTENCIA

async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_potencia"] = update.message.text
    await update.message.reply_text("Qual o seu *Telefone* (com DDD)?", parse_mode="Markdown")
    return TELEFONE

async def receber_telefone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cadastro_telefone"] = update.message.text
    await update.message.reply_text("Obrigado! Confirmando seus dados. Digite 'confirmar' para finalizar o cadastro.", parse_mode="Markdown")
    return FINALIZAR

async def finalizar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.lower() == "confirmar":
        dados_membro = {
            "nome": context.user_data["cadastro_nome"],
            "loja": context.user_data["cadastro_loja"],
            "grau": context.user_data["cadastro_grau"],
            "oriente": context.user_data["cadastro_oriente"],
            "potencia": context.user_data["cadastro_potencia"],
            "telefone": context.user_data["cadastro_telefone"],
            "telegram_id": update.effective_user.id,
            "cargo": "",
        }
        cadastrar_membro(dados_membro)
        
        # Verifica se há uma ação pendente após o cadastro (ex: confirmar presença)
        if "pos_cadastro" in context.user_data:
            acao = context.user_data["pos_cadastro"]
            if acao.get("acao") == "confirmar":
                from src.eventos import iniciar_confirmacao_presenca_pos_cadastro
                await iniciar_confirmacao_presenca_pos_cadastro(update, context, acao)
                context.user_data.pop("pos_cadastro", None)
                return ConversationHandler.END
        
        await update.message.reply_text(
            "✅ Cadastro realizado com sucesso! Bem-vindo, irmão!\n\n"
            "Use /start para acessar o menu principal."
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Por favor, digite 'confirmar' para finalizar ou /cancelar para abortar.")
        return FINALIZAR

async def cancelar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cadastro cancelado. Você pode iniciar novamente com /start.")
    return ConversationHandler.END

cadastro_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", cadastro_start),
        CallbackQueryHandler(cadastro_start, pattern="^iniciar_cadastro$")
    ],
    states={
        NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)],
        LOJA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_loja)],
        GRAU: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_grau)],
        ORIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_oriente)],
        POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_potencia)],
        TELEFONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_telefone)],
        FINALIZAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalizar_cadastro)],
    },
    fallbacks=[CommandHandler("cancelar", cancelar_cadastro)],
)