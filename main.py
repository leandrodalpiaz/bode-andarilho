# main.py
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# Importações dos seus módulos
from src.bot import start, botao_handler
from src.cadastro import cadastro_handler
from src.eventos import mostrar_eventos, mostrar_detalhes_evento, cancelar_presenca, confirmacao_presenca_handler # Importa o ConversationHandler
from src.cadastro_evento import cadastro_evento_handler

import os

TOKEN = os.getenv("TELEGRAM_TOKEN")
app = ApplicationBuilder().token(TOKEN).build()

# Handler para o comando /start
app.add_handler(CommandHandler("start", start))

# Handler de Cadastro de Membros (ConversationHandler)
app.add_handler(cadastro_handler)

# Handler de Cadastro de Eventos (ConversationHandler)
app.add_handler(cadastro_evento_handler)

# NOVO: Handler de Confirmação de Presença (ConversationHandler)
app.add_handler(confirmacao_presenca_handler)

# Handlers de Eventos (botões de callback que não iniciam ConversationHandler)
app.add_handler(CallbackQueryHandler(mostrar_eventos, pattern="^ver_eventos$"))
app.add_handler(CallbackQueryHandler(mostrar_detalhes_evento, pattern="^evento_"))
app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern="^cancelar_")) # Cancelar presença é um handler simples agora

# Handler genérico para botões que não se encaixam nos padrões acima
app.add_handler(CallbackQueryHandler(botao_handler))


print("Bot rodando...")
app.run_polling(allowed_updates=Update.ALL_TYPES)
