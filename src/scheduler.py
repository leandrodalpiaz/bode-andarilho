import logging
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from src.lembretes import (
    enviar_celebracao_mensal,
    enviar_lembretes_24h,
    enviar_lembretes_meio_dia,
)
from src.eventos import flush_notificacoes_secretario_adiadas


logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def job_lembretes_24h(app: Application):
    await enviar_lembretes_24h(app.bot)


async def job_lembretes_meio_dia(app: Application):
    await enviar_lembretes_meio_dia(app.bot)


async def job_celebracao_mensal(app: Application):
    """Roda no primeiro dia de cada mês às 09:00."""
    await enviar_celebracao_mensal(app.bot)


async def job_flush_notificacoes_secretario(app: Application):
    """Consolida e envia notificações acumuladas do período silencioso."""
    await flush_notificacoes_secretario_adiadas(app.bot)


async def job_aniversarios_cadastro(app: Application):
    """Job diário para calcular tempo de casa e conceder conquistas de aniversário."""
    try:
        from src.conquistas import checar_aniversarios_cadastro
        await checar_aniversarios_cadastro(app.bot)
    except Exception as e:
        logger.error("Erro ao executar crawler de aniversários de cadastro: %s", e)


async def job_limpeza_midias_passadas(app: Application):
    """Job diário para apagar imagens físicas de eventos passados do Storage."""
    try:
        import asyncio
        from src.sheets_supabase import limpar_midias_eventos_passados
        removidos = await asyncio.to_thread(limpar_midias_eventos_passados)
        if removidos > 0:
            logger.info("Job de efemeridade concluiu a limpeza de %d arquivos.", removidos)
    except Exception as e:
        logger.error("Erro ao executar job de limpeza de mídias passadas: %s", e)


async def job_faxina_membros(app: Application):
    """
    Job semanal de faxina de membros.
    Verifica se os membros cadastrados com status 'Ativo' continuam no grupo principal.
    Caso contrário, altera seu status para 'Inativo'.
    """
    import os
    from src.sheets_supabase import listar_membros_ativos, marcar_como_inativo

    grupo_id_str = os.getenv("GRUPO_PRINCIPAL_ID", "")
    if not grupo_id_str or not grupo_id_str.lstrip("-").isdigit():
        logger.warning("Job de faxina abortado: GRUPO_PRINCIPAL_ID não configurado corretamente.")
        return

    grupo_id = int(grupo_id_str)

    try:
        membros = await asyncio.to_thread(listar_membros_ativos)
    except Exception as e:
        logger.error("Erro ao buscar membros ativos para a faxina: %s", e)
        return

    if not membros:
        logger.info("Nenhum membro ativo para validar no job de faxina.")
        return

    logger.info("Iniciando faxina de %d membros ativos...", len(membros))
    processados = 0
    inativados = 0

    for m in membros:
        user_id_str = m.get("Telegram ID") or m.get("telegram_id")
        if not user_id_str:
            continue

        try:
            user_id = int(float(user_id_str))
        except Exception:
            continue

        try:
            # Rate limiting suave para evitar flood do Telegram API
            await asyncio.sleep(0.2)

            member = await app.bot.get_chat_member(chat_id=grupo_id, user_id=user_id)
            esta_no_grupo = member.status in ("member", "administrator", "creator")

            if not esta_no_grupo:
                logger.info(
                    "Membro %s (%s) saiu do grupo (status: %s). Inativando...",
                    m.get("Nome"),
                    user_id,
                    member.status,
                )
                await asyncio.to_thread(marcar_como_inativo, user_id)
                inativados += 1

        except Exception as e:
            msg = str(e).lower()
            # Se o erro for do chat inexistente ou bot expulso, aborte!
            if "chat not found" in msg or "bot was kicked" in msg or "not member of the chat" in msg:
                logger.critical("Job de faxina abortado por erro crítico no chat %s: %s", grupo_id, e)
                return

            # Erros de usuário (user not found / user_id_invalid)
            if "user not found" in msg or "invalid user" in msg:
                logger.info(
                    "Membro %s (%s) não localizado no chat (erro: %s). Inativando...",
                    m.get("Nome"),
                    user_id,
                    e,
                )
                await asyncio.to_thread(marcar_como_inativo, user_id)
                inativados += 1
            else:
                logger.warning("Erro ao verificar membro %s (%s) no chat: %s", m.get("Nome"), user_id, e)

        processados += 1

    logger.info(
        "Faxina concluída! Processados: %d/%d membros. Inativados: %d.",
        processados,
        len(membros),
        inativados,
    )


async def iniciar_scheduler(app: Application):
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("Scheduler já estava ativo; mantendo instância atual.")
        return

    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")

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
    scheduler.add_job(
        job_aniversarios_cadastro,
        "cron",
        hour=9,
        minute=30,
        args=[app],
        id="job_aniversarios_cadastro",
        replace_existing=True,
    )
    scheduler.add_job(
        job_flush_notificacoes_secretario,
        "cron",
        hour=7,
        minute=0,
        args=[app],
        id="job_flush_notificacoes_secretario",
        replace_existing=True,
    )
    scheduler.add_job(
        job_limpeza_midias_passadas,
        "cron",
        hour=4,
        minute=0,
        args=[app],
        id="job_limpeza_midias_passadas",
        replace_existing=True,
    )
    scheduler.add_job(
        job_faxina_membros,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        args=[app],
        id="job_faxina_membros",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler iniciado com jobs de lembretes, celebração mensal, flush e faxina semanal."
    )