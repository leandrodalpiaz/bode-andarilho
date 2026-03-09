import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from src.lembretes import (
    enviar_celebracao_mensal,
    enviar_lembretes_24h,
    enviar_lembretes_meio_dia,
)


logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def job_lembretes_24h(app: Application):
    await enviar_lembretes_24h(app.bot)


async def job_lembretes_meio_dia(app: Application):
    await enviar_lembretes_meio_dia(app.bot)


async def job_celebracao_mensal(app: Application):
    """Roda no primeiro dia de cada mês às 09:00."""
    await enviar_celebracao_mensal(app.bot)


async def iniciar_scheduler(app: Application):
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("Scheduler já estava ativo; mantendo instância atual.")
        return

    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        job_lembretes_24h,
        "cron",
        hour=8,
        minute=0,
        args=[app],
        id="job_lembretes_24h",
        replace_existing=True,
    )
    scheduler.add_job(
        job_lembretes_meio_dia,
        "cron",
        hour=12,
        minute=0,
        args=[app],
        id="job_lembretes_meio_dia",
        replace_existing=True,
    )
    scheduler.add_job(
        job_celebracao_mensal,
        "cron",
        day="1",
        hour=9,
        minute=0,
        args=[app],
        id="job_celebracao_mensal",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler iniciado com jobs de lembretes e celebração mensal.")