# src/scheduler.py
import asyncio
from datetime import datetime, timedelta, time
from telegram.ext import Application
from src.lembretes import enviar_lembretes

async def job_lembretes(app: Application):
    """Executa todos os dias às 8h"""
    while True:
        agora = datetime.now()
        alvo = time(8, 0)  # 8:00 AM
        proximo = datetime.combine(agora.date(), alvo)
        
        if agora > proximo:
            proximo += timedelta(days=1)
        
        segundos_ate_execucao = (proximo - agora).total_seconds()
        await asyncio.sleep(segundos_ate_execucao)
        
        try:
            await enviar_lembretes(app.bot)
            print(f"[{datetime.now()}] Lembretes enviados com sucesso")
        except Exception as e:
            print(f"[{datetime.now()}] Erro ao enviar lembretes: {e}")

async def iniciar_scheduler(app: Application):
    """Inicia o scheduler em background"""
    asyncio.create_task(job_lembretes(app))
    print("Scheduler de lembretes iniciado")