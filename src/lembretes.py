# src/lembretes.py
from datetime import datetime, timedelta
from telegram import Bot
from src.sheets import listar_eventos, listar_confirmacoes_por_evento
from src.messages import LEMBRETE_TITULO, LEMBRETE_CORPO

async def enviar_lembretes_24h(bot: Bot):
    """
    Envia lembretes 24h antes do evento (execução às 8h da manhã)
    """
    hoje = datetime.now()
    amanha = hoje + timedelta(days=1)
    amanha_str = amanha.strftime("%d/%m")

    eventos = listar_eventos()

    for evento in eventos:
        data_evento = evento.get("Data do evento", "")
        if data_evento != amanha_str:
            continue

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

        for membro in confirmados:
            telegram_id = membro.get("Telegram ID", "")
            nome = membro.get("Nome", "")
            if not telegram_id:
                continue

            texto = (
                f"🐐 *Lembrete de evento — Bode Andarilho*\n\n"
                f"Olá, irmão {nome}! Você confirmou presença no seguinte evento:\n\n"
                f"📅 Data: {data_evento}\n"
                f"🏛️ Loja: {nome_loja}{numero_fmt}\n"
                f"🕐 Horário: {horario}\n"
                f"📍 Local: {local}\n"
                f"🔷 Grau mínimo: {grau}\n"
                f"👔 Traje: {traje}\n"
                f"🍽️ Ágape: {agape}\n\n"
                f"Até amanhã! 🤝"
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


async def enviar_lembretes_meio_dia(bot: Bot):
    """
    Envia lembretes ao meio-dia do dia do evento
    """
    hoje = datetime.now()
    hoje_str = hoje.strftime("%d/%m")

    eventos = listar_eventos()

    for evento in eventos:
        data_evento = evento.get("Data do evento", "")
        if data_evento != hoje_str:
            continue

        id_evento = data_evento + " — " + evento.get("Nome da loja", "")
        confirmados = listar_confirmacoes_por_evento(id_evento)

        nome_loja = evento.get("Nome da loja", "")
        numero_loja = evento.get("Número da loja", "")
        horario = evento.get("Hora", "")
        local = evento.get("Endereço da sessão", "")
        numero_fmt = f" {numero_loja}" if numero_loja else ""

        for membro in confirmados:
            telegram_id = membro.get("Telegram ID", "")
            nome = membro.get("Nome", "")
            if not telegram_id:
                continue

            texto = (
                f"🕛 *MEIO DIA EM PONTO!*\n\n"
                f"Irmão {nome}, hoje tem sessão!\n\n"
                f"🏛 Loja {nome_loja}{numero_fmt}\n"
                f"📍 {local}\n"
                f"🕕 {horario}\n\n"
                f"Até logo mais! 🤝"
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