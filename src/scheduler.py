# src/scheduler.py
import asyncio
from datetime import datetime, timedelta, time
from telegram.ext import Application
from src.lembretes import enviar_lembretes_24h, enviar_lembretes_meio_dia

async def job_lembretes_24h(app: Application):
    """Executa todos os dias às 8h para lembretes de 24h antes"""
    while True:
        agora = datetime.now()
        alvo = time(8, 0)  # 8:00 AM
        proximo = datetime.combine(agora.date(), alvo)
        
        if agora > proximo:
            proximo += timedelta(days=1)
        
        segundos_ate_execucao = (proximo - agora).total_seconds()
        await asyncio.sleep(segundos_ate_execucao)
        
        try:
            await enviar_lembretes_24h(app.bot)
            print(f"[{datetime.now()}] Lembretes de 24h enviados com sucesso")
        except Exception as e:
            print(f"[{datetime.now()}] Erro ao enviar lembretes de 24h: {e}")


async def job_lembretes_meio_dia(app: Application):
    """Executa todos os dias às 12:00 para lembretes do meio-dia"""
    while True:
        agora = datetime.now()
        alvo = time(12, 0)  # 12:00 PM
        proximo = datetime.combine(agora.date(), alvo)
        
        if agora > proximo:
            proximo += timedelta(days=1)
        
        segundos_ate_execucao = (proximo - agora).total_seconds()
        await asyncio.sleep(segundos_ate_execucao)
        
        try:
            await enviar_lembretes_meio_dia(app.bot)
            print(f"[{datetime.now()}] Lembretes de meio-dia enviados com sucesso")
        except Exception as e:
            print(f"[{datetime.now()}] Erro ao enviar lembretes de meio-dia: {e}")


async def iniciar_scheduler(app: Application):
    """Inicia os schedulers em background"""
    asyncio.create_task(job_lembretes_24h(app))
    asyncio.create_task(job_lembretes_meio_dia(app))
    print("✅ Schedulers de lembretes iniciados (execuções diárias às 8h e 12h)")