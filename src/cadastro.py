from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, filters
)
from src.sheets import buscar_membro, cadastrar_membro
from src.permissoes import get_nivel

NOME, LOJA, GRAU, ORIENTE, POTENCIA = range(5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.bot import menu_principal_teclado
    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if membro:
        nivel = get_nivel(telegram_id)
        await update.message.reply_text(
            f"Bem-vindo de volta, irmão {membro.get('Nome', '')}! 🐐\n\nO que deseja fazer?",
            reply_markup=menu_principal_teclado(nivel)
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Olá! Bem-vindo ao bot do Bode Andarilho. 🐐\n\n"
        "Vou precisar de algumas informações para te cadastrar.\n\n"
        "Qual é o seu nome completo?"
    )
    return NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nome"] = update.message.text
    await update.message.reply_text("Qual é o nome da sua loja de origem?")
    return LOJA

async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["loja"] = update.message.text
    await update.message.reply_text("Qual é o seu grau? (Aprendiz, Companheiro ou Mestre)")
    return GRAU

async def receber_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["grau"] = update.message.text
    await update.message.reply_text("Qual é o oriente da sua loja? (cidade)")
    return ORIENTE

async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["oriente"] = update.message.text
    await update.message.reply_text("Qual é a potência da sua loja? (ex: GOB, GLESP, COMAB...)")
    return POTENCIA

async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.bot import menu_principal_teclado
    context.user_data["potencia"] = update.message.text
    telegram_id = update.effective_user.id

    dados = {
        "telegram_id": telegram_id,
        "nome": context.user_data.get("nome", ""),
        "loja": context.user_data.get("loja", ""),
        "grau": context.user_data.get("grau", ""),
        "oriente": context.user_data.get("oriente", ""),
        "potencia": context.user_data.get("potencia", ""),
    }

    cadastrar_membro(dados)
    nivel = get_nivel(telegram_id)

    await update.message.reply_text(
        f"Cadastro realizado com sucesso, irmão {dados['nome']}! 🐐\n\n"
        f"Bem-vindo ao Bode Andarilho!\n\nO que deseja fazer?",
        reply_markup=menu_principal_teclado(nivel)
    )
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cadastro cancelado.")
    return ConversationHandler.END

cadastro_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)],
        LOJA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_loja)],
        GRAU: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_grau)],
        ORIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_oriente)],
        POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_potencia)],
    },
    fallbacks=[CommandHandler("cancelar", cancelar)]
)
