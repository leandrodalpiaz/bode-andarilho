from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, filters
from src.cadastro import cadastro_handler
from src.bot import botao_handler
from src.cadastro_evento import cadastro_evento_handler
import os

TOKEN = os.getenv("TELEGRAM_TOKEN")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(cadastro_handler)
app.add_handler(cadastro_evento_handler)
app.add_handler(CallbackQueryHandler(botao_handler))

print("Bot rodando...")
app.run_polling()
