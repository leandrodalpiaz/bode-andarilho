from datetime import datetime, timedelta
from telegram import Bot
from src.sheets import listar_eventos, listar_confirmacoes

async def enviar_lembretes(bot: Bot):
    hoje = datetime.now()
    amanha = hoje + timedelta(days=1)
    amanha_str = amanha.strftime("%d/%m")

    eventos = listar_eventos()

    for evento in eventos:
        data_evento = evento.get("Data do evento", "")
        if data_evento != amanha_str:
            continue

        id_evento = data_evento + " — " + evento.get("Nome da loja", "")
        confirmados = listar_confirmacoes(id_evento)

        nome_loja = evento.get("Nome da loja", "")
        horario = evento.get("Hora", "")
        local = evento.get("Local", "")
        grau = evento.get("Grau mínimo", "")
        traje = evento.get("Traje obrigatório", "")
        agape = evento.get("Ágape", "")

        for membro in confirmados:
            telegram_id = membro.get("Telegram ID", "")
            nome = membro.get("Nome", "")
            if not telegram_id:
                continue

            texto = (
                f"🐐 *Lembrete de evento — Bode Andarilho*\n\n"
                f"Olá, irmão {nome}! Você confirmou presença no seguinte evento:\n\n"
                f"📅 Data: {data_evento}\n"
                f"🏛️ Loja: {nome_loja}\n"
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
            except Exception as e:
                print(f"Erro ao enviar lembrete para {telegram_id}: {e}")
