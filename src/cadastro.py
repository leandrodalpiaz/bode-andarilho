# src/cadastro.py
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CommandHandler, filters
from src.sheets import buscar_membro, cadastrar_membro # Importa funções de sheets
from src.bot import start # Importa a função start do bot para o fallback

# Estados da conversação para o cadastro de membro
NOME, LOJA, GRAU, ORIENTE, POTENCIA, TELEFONE, FINALIZAR = range(7)

async def cadastro_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "Para editar seu cadastro, entre em contato com um administrador."
        )
        # Se já cadastrado, encerra o ConversationHandler e retorna ao menu principal
        from src.bot import menu_principal_teclado # Importa aqui para evitar circular
        nivel = membro.get("Nivel", "membro") # Assumindo que o nível está no cadastro
        await update.message.reply_text(
            "O que deseja fazer?",
            reply_markup=menu_principal_teclado(nivel)
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
            "nivel": "membro", # Nível padrão ao cadastrar
        }
        cadastrar_membro(dados_membro)
        await update.message.reply_text("✅ Cadastro realizado com sucesso! Bem-vindo, irmão!")
        # Após o cadastro, mostra o menu principal
        from src.bot import menu_principal_teclado
        await update.message.reply_text(
            "O que deseja fazer?",
            reply_markup=menu_principal_teclado("membro") # Nível padrão
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Por favor, digite 'confirmar' para finalizar ou /cancelar para abortar.")
        return FINALIZAR

async def cancelar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cadastro cancelado.")
    return ConversationHandler.END

# O ConversationHandler para o cadastro de membros
cadastro_handler = ConversationHandler(
    entry_points=[CommandHandler("start", cadastro_start)], # O /start inicia o cadastro se não for cadastrado
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
