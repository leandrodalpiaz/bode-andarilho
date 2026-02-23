import os
import asyncio
import sys
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.cadastro import cadastro_handler
from src.bot import botao_handler
from src.lembretes import enviar_lembretes

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

async def post_init(application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        enviar_lembretes,
        trigger="cron",
        hour=9,
        minute=0,
        args=[application.bot]
    )
    scheduler.start()
    print("Agendador de lembretes iniciado!")

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(cadastro_handler)
    app.add_handler(CallbackQueryHandler(botao_handler))
    print("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
