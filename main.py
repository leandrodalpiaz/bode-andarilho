import os
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler
from src.bot import start, botao_handler

# Carrega as variáveis do arquivo .env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Registra os handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(botao_handler))

    print("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
