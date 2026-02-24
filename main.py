# main.py
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

# Importações dos módulos existentes
from src.bot import start, botao_handler
from src.cadastro import cadastro_handler
from src.eventos import mostrar_eventos, mostrar_detalhes_evento, cancelar_presenca, confirmacao_presenca_handler
from src.cadastro_evento import cadastro_evento_handler
from src.admin_acoes import promover_handler, rebaixar_handler  # NOVOS HANDLERS

import os

TOKEN = os.getenv("TELEGRAM_TOKEN")
app = ApplicationBuilder().token(TOKEN).build()

# Handlers existentes
app.add_handler(CommandHandler("start", start))
app.add_handler(cadastro_handler)
app.add_handler(cadastro_evento_handler)
app.add_handler(confirmacao_presenca_handler)

# NOVOS handlers de promoção/rebaixamento
app.add_handler(promover_handler)
app.add_handler(rebaixar_handler)

# Handlers de botões simples
app.add_handler(CallbackQueryHandler(mostrar_eventos, pattern="^ver_eventos$"))
app.add_handler(CallbackQueryHandler(mostrar_detalhes_evento, pattern="^evento_"))
app.add_handler(CallbackQueryHandler(cancelar_presenca, pattern="^cancelar_"))
app.add_handler(CallbackQueryHandler(botao_handler))  # genérico (deve vir por último)

print("Bot rodando...")
app.run_polling(allowed_updates=Update.ALL_TYPES)