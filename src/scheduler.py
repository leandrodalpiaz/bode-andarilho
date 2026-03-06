# src/scheduler.py
# ============================================
# BODE ANDARILHO - AGENDADOR DE TAREFAS AUTOMÁTICAS
# ============================================
# 
# Este módulo gerencia a execução de tarefas agendadas em background.
# Atualmente, controla o envio de lembretes automáticos para os membros.
# 
# Tarefas agendadas:
# 1. job_lembretes_24h: Executa diariamente às 8:00
#    - Envia lembretes para eventos do dia seguinte
# 
# 2. job_lembretes_meio_dia: Executa diariamente às 12:00
#    - Envia lembretes especiais para eventos do dia
# 
# O scheduler roda em segundo plano enquanto o bot está ativo,
# utilizando asyncio para não bloquear o processamento principal.
# 
# ============================================

import asyncio
from datetime import datetime, timedelta, time
from telegram.ext import Application
from src.lembretes import enviar_lembretes_24h, enviar_lembretes_meio_dia


# ============================================
# JOB DE LEMBRETES 24H ANTES
# ============================================

async def job_lembretes_24h(app: Application):
    """
    Executa todos os dias às 8:00 para enviar lembretes de 24h antes.
    
    O job calcula o próximo horário de execução (8:00 do dia seguinte
    se já passou das 8:00 hoje) e aguarda até lá.
    
    Args:
        app (Application): Instância da aplicação do Telegram
    """
    while True:
        agora = datetime.now()
        alvo = time(8, 0)  # 8:00 AM
        proximo = datetime.combine(agora.date(), alvo)
        
        # Se já passou das 8:00 hoje, agenda para amanhã
        if agora > proximo:
            proximo += timedelta(days=1)
        
        segundos_ate_execucao = (proximo - agora).total_seconds()
        await asyncio.sleep(segundos_ate_execucao)
        
        try:
            await enviar_lembretes_24h(app.bot)
            print(f"[{datetime.now()}] Lembretes de 24h enviados com sucesso")
        except Exception as e:
            print(f"[{datetime.now()}] Erro ao enviar lembretes de 24h: {e}")


# ============================================
# JOB DE LEMBRETES DE MEIO-DIA
# ============================================

async def job_lembretes_meio_dia(app: Application):
    """
    Executa todos os dias às 12:00 para enviar lembretes de meio-dia.
    
    Args:
        app (Application): Instância da aplicação do Telegram
    """
    while True:
        agora = datetime.now()
        alvo = time(12, 0)  # 12:00 PM
        proximo = datetime.combine(agora.date(), alvo)
        
        # Se já passou das 12:00 hoje, agenda para amanhã
        if agora > proximo:
            proximo += timedelta(days=1)
        
        segundos_ate_execucao = (proximo - agora).total_seconds()
        await asyncio.sleep(segundos_ate_execucao)
        
        try:
            await enviar_lembretes_meio_dia(app.bot)
            print(f"[{datetime.now()}] Lembretes de meio-dia enviados com sucesso")
        except Exception as e:
            print(f"[{datetime.now()}] Erro ao enviar lembretes de meio-dia: {e}")


# ============================================
# INICIALIZAÇÃO DOS SCHEDULERS
# ============================================

async def iniciar_scheduler(app: Application):
    """
    Inicia os schedulers em background.
    
    Esta função deve ser chamada durante a inicialização do bot
    (no main.py) para começar o agendamento das tarefas.
    
    Args:
        app (Application): Instância da aplicação do Telegram
    """
    # Cria tasks assíncronas para cada job
    asyncio.create_task(job_lembretes_24h(app))
    asyncio.create_task(job_lembretes_meio_dia(app))
    
    print("✅ Schedulers de lembretes iniciados (execuções diárias às 8h e 12h)")