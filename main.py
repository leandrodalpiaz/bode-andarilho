import os
import asyncio
import sys
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CallbackQueryHandler
from src.cadastro import cadastro_handler
from src.bot import botao_handler

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(cadastro_handler)
    app.add_handler(CallbackQueryHandler(botao_handler))
    print("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
