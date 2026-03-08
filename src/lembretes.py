# src/lembretes.py
# ============================================
# BODE ANDARILHO - SISTEMA DE LEMBRETES AUTOMÁTICOS
# ============================================
# 
# Este módulo gerencia o envio de lembretes automáticos para
# os membros que confirmaram presença em eventos.
# 
# Dois tipos de lembretes:
# 1. 24h antes do evento (enviado às 8h da manhã do dia anterior)
# 2. Meio-dia do dia do evento (enviado às 12h)
# 
# Os lembretes são disparados pelo scheduler.py e utilizam
# as mensagens centralizadas em messages.py.
# 
# ============================================

from datetime import datetime, timedelta
from telegram import Bot
from src.sheets import listar_eventos, listar_confirmacoes_por_evento
from src.messages import (
    LEMBRETE_TITULO,
    LEMBRETE_CORPO,
    LEMBRETE_MEIO_DIA_TITULO,
    LEMBRETE_MEIO_DIA_CORPO,
    LEMBRETE_SECRETARIO_TITULO,
    LEMBRETE_SECRETARIO_CORPO,
    LEMBRETE_SECRETARIO_MEIO_DIA_TITULO,
    LEMBRETE_SECRETARIO_MEIO_DIA_CORPO
)


# ============================================
# LEMBRETE DE 24H ANTES
# ============================================

async def enviar_lembretes_24h(bot: Bot):
    """
    Envia lembretes 24h antes do evento.
    Executado pelo scheduler às 8h da manhã.
    
    Fluxo:
    1. Calcula a data de amanhã
    2. Busca todos os eventos desta data
    3. Para cada evento, busca os confirmados
    4. Envia mensagem personalizada para cada confirmado
    """
    hoje = datetime.now()
    amanha = hoje + timedelta(days=1)
    amanha_str = amanha.strftime("%d/%m")

    eventos = listar_eventos()

    for evento in eventos:
        data_evento = evento.get("Data do evento", "")
        if data_evento != amanha_str:
            continue

        # Gera ID do evento (fallback para compatibilidade)
        id_evento = data_evento + " — " + evento.get("Nome da loja", "")
        confirmados = listar_confirmacoes_por_evento(id_evento)

        nome_loja = evento.get("Nome da loja", "")
        numero_loja = evento.get("Número da loja", "")
        horario = evento.get("Hora", "")
        local = evento.get("Endereço da sessão", "")
        grau = evento.get("Grau", "")
        traje = evento.get("Traje obrigatório", "")
        agape = evento.get("Ágape", "")
        numero_fmt = f" {numero_loja}" if numero_loja else ""

        # Envia lembretes para confirmados
        for membro in confirmados:
            telegram_id = membro.get("Telegram ID", "")
            nome = membro.get("Nome", "")
            if not telegram_id:
                continue

            # Monta mensagem usando template
            texto = (
                f"{LEMBRETE_TITULO}\n\n"
                f"{LEMBRETE_CORPO.format(
                    nome=nome,
                    data=data_evento,
                    loja=nome_loja,
                    horario=horario,
                    local=local,
                    grau=grau,
                    traje=traje,
                    agape=agape
                )}"
            )

            try:
                await bot.send_message(
                    chat_id=int(telegram_id),
                    text=texto,
                    parse_mode="Markdown"
                )
                print(f"Lembrete 24h enviado para {nome} ({telegram_id})")
            except Exception as e:
                print(f"Erro ao enviar lembrete 24h para {telegram_id}: {e}")

        # Envia lembrete para o secretário
        secretario_id = evento.get("Telegram ID do secretário", "")
        if secretario_id:
            from src.sheets import buscar_membro
            secretario = buscar_membro(int(secretario_id))
            if secretario:
                nome_secretario = secretario.get("Nome", "")
                num_confirmados = len(confirmados)
                
                texto_secretario = (
                    f"{LEMBRETE_SECRETARIO_TITULO}\n\n"
                    f"{LEMBRETE_SECRETARIO_CORPO.format(
                        nome=nome_secretario,
                        data=data_evento,
                        loja=nome_loja,
                        horario=horario,
                        local=local,
                        grau=grau,
                        traje=traje,
                        agape=agape,
                        num_confirmados=num_confirmados
                    )}"
                )

                try:
                    await bot.send_message(
                        chat_id=int(secretario_id),
                        text=texto_secretario,
                        parse_mode="Markdown"
                    )
                    print(f"Lembrete 24h enviado para secretário {nome_secretario} ({secretario_id})")
                except Exception as e:
                    print(f"Erro ao enviar lembrete 24h para secretário {secretario_id}: {e}")


# ============================================
# LEMBRETE DE MEIO-DIA
# ============================================

async def enviar_lembretes_meio_dia(bot: Bot):
    """
    Envia lembretes ao meio-dia do dia do evento.
    Executado pelo scheduler às 12h.
    
    Fluxo:
    1. Calcula a data de hoje
    2. Busca todos os eventos desta data
    3. Para cada evento, busca os confirmados
    4. Envia mensagem especial de meio-dia
    """
    hoje = datetime.now()
    hoje_str = hoje.strftime("%d/%m")

    eventos = listar_eventos()

    for evento in eventos:
        data_evento = evento.get("Data do evento", "")
        if data_evento != hoje_str:
            continue

        # Gera ID do evento (fallback para compatibilidade)
        id_evento = data_evento + " — " + evento.get("Nome da loja", "")
        confirmados = listar_confirmacoes_por_evento(id_evento)

        nome_loja = evento.get("Nome da loja", "")
        numero_loja = evento.get("Número da loja", "")
        horario = evento.get("Hora", "")
        local = evento.get("Endereço da sessão", "")
        numero_fmt = f" {numero_loja}" if numero_loja else ""

        # Envia lembretes para confirmados
        for membro in confirmados:
            telegram_id = membro.get("Telegram ID", "")
            nome = membro.get("Nome", "")
            if not telegram_id:
                continue

            # Monta mensagem usando template
            texto = (
                f"{LEMBRETE_MEIO_DIA_TITULO}\n\n"
                f"{LEMBRETE_MEIO_DIA_CORPO.format(
                    nome=nome,
                    loja=nome_loja,
                    numero=numero_fmt,
                    local=local,
                    horario=horario
                )}"
            )

            try:
                await bot.send_message(
                    chat_id=int(telegram_id),
                    text=texto,
                    parse_mode="Markdown"
                )
                print(f"Lembrete meio-dia enviado para {nome} ({telegram_id})")
            except Exception as e:
                print(f"Erro ao enviar lembrete meio-dia para {telegram_id}: {e}")

        # Envia lembrete para o secretário
        secretario_id = evento.get("Telegram ID do secretário", "")
        if secretario_id:
            from src.sheets import buscar_membro
            secretario = buscar_membro(int(secretario_id))
            if secretario:
                nome_secretario = secretario.get("Nome", "")
                num_confirmados = len(confirmados)
                
                texto_secretario = (
                    f"{LEMBRETE_SECRETARIO_MEIO_DIA_TITULO}\n\n"
                    f"{LEMBRETE_SECRETARIO_MEIO_DIA_CORPO.format(
                        nome=nome_secretario,
                        loja=nome_loja,
                        numero=numero_fmt,
                        local=local,
                        horario=horario,
                        num_confirmados=num_confirmados
                    )}"
                )

                try:
                    await bot.send_message(
                        chat_id=int(secretario_id),
                        text=texto_secretario,
                        parse_mode="Markdown"
                    )
                    print(f"Lembrete meio-dia enviado para secretário {nome_secretario} ({secretario_id})")
                except Exception as e:
                    print(f"Erro ao enviar lembrete meio-dia para secretário {secretario_id}: {e}")