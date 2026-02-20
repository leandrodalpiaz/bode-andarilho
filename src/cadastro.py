from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
)
from src.sheets import buscar_membro, cadastrar_membro
from src.messages import BOAS_VINDAS, BOAS_VINDAS_RETORNO, MENU_PRINCIPAL
from src.bot import menu_principal_teclado

NOME, LOJA, GRAU, ORIENTE, POTENCIA = range(5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    membro = buscar_membro(telegram_id)

    if membro:
        await update.message.reply_text(
            BOAS_VINDAS_RETORNO.format(nome=membro["Nome"]),
            reply_markup=menu_principal_teclado()
        )
        return ConversationHandler.END

    await update.message.reply_text(BOAS_VINDAS)
    await update.message.reply_text("Qual é o seu nome completo, irmão?")
    return NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nome"] = update.message.text.strip()
    await update.message.reply_text("Qual é o nome da sua loja?")
    return LOJA

async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["loja"] = update.message.text.strip()
    await update.message.reply_text(
        "Qual é o seu grau?\n\n1 — Aprendiz\n2 — Companheiro\n3 — Mestre"
    )
    return GRAU

async def receber_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["grau"] = update.message.text.strip()
    await update.message.reply_text("Qual é o seu oriente? (cidade da sua loja)")
    return ORIENTE

async def receber_oriente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["oriente"] = update.message.text.strip()
    await update.message.reply_text("Qual é a sua potência? (ex: GOB, GOBR, GLMB...)")
    return POTENCIA

async def receber_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["potencia"] = update.message.text.strip()

    dados = {
        "telegram_id": update.effective_user.id,
        "nome": context.user_data["nome"],
        "loja": context.user_data["loja"],
        "grau": context.user_data["grau"],
        "oriente": context.user_data["oriente"],
        "potencia": context.user_data["potencia"],
    }
    cadastrar_membro(dados)

    await update.message.reply_text(
        f"Cadastro realizado, irmão {dados['nome']}! Bem-vindo ao Bode Andarilho. 🐐",
        reply_markup=menu_principal_teclado()
    )
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cadastro cancelado. Envie /start para recomeçar.")
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
    fallbacks=[CommandHandler("cancelar", cancelar)],
)
