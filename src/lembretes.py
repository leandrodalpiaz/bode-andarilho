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
import logging
from os import getenv

from telegram import Bot
from src.sheets_supabase import (
    listar_eventos,
    listar_confirmacoes_por_evento,
    buscar_membro,
    buscar_confirmacoes_no_periodo,
    buscar_eventos_no_periodo,
)
from src.messages import (
    LEMBRETE_TITULO,
    LEMBRETE_CORPO,
    LEMBRETE_MEIO_DIA_TITULO,
    LEMBRETE_MEIO_DIA_CORPO,
    LEMBRETE_SECRETARIO_TITULO,
    LEMBRETE_SECRETARIO_CORPO,
    LEMBRETE_SECRETARIO_MEIO_DIA_TITULO,
    LEMBRETE_SECRETARIO_MEIO_DIA_CORPO,
    TEXTO_CELEBRACAO_MENSAL,
)


logger = logging.getLogger(__name__)


def _parse_telegram_id(valor) -> int | None:
    """Normaliza Telegram ID aceitando formatos legados como '12345.0'."""
    try:
        s = str(valor or "").strip()
        if not s:
            return None
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _parse_data_evento(texto_data: str):
    """Aceita datas em DD/MM/YYYY e formato legado DD/MM."""
    texto_data = str(texto_data or "").strip()
    if not texto_data:
        return None

    formatos = ("%d/%m/%Y", "%d/%m")
    for fmt in formatos:
        try:
            return datetime.strptime(texto_data, fmt)
        except ValueError:
            continue
    return None


def _mesmo_dia(data_evento_str: str, data_alvo: datetime) -> bool:
    dt_evento = _parse_data_evento(data_evento_str)
    if not dt_evento:
        return False

    # Datas sem ano (legado DD/MM) vêm com ano 1900.
    if dt_evento.year == 1900:
        return dt_evento.day == data_alvo.day and dt_evento.month == data_alvo.month

    return dt_evento.date() == data_alvo.date()


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

    eventos = listar_eventos()

    for evento in eventos:
        data_evento = str(evento.get("Data do evento", "") or "").strip()
        if not _mesmo_dia(data_evento, amanha):
            continue

        # Gera ID do evento (preferencialmente da coluna ID Evento, fallback para compatibilidade)
        id_evento = str(evento.get("ID Evento", "")).strip() or (data_evento + " — " + evento.get("Nome da loja", ""))
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
                + LEMBRETE_CORPO.format(
                    nome=nome,
                    data=data_evento,
                    loja=nome_loja,
                    horario=horario,
                    local=local,
                    grau=grau,
                    traje=traje,
                    agape=agape,
                )
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
        secretario_id = _parse_telegram_id(evento.get("Telegram ID do secretário", ""))
        if secretario_id:
            secretario = buscar_membro(secretario_id)
            if secretario:
                nome_secretario = secretario.get("Nome", "")
                num_confirmados = len(confirmados)
                
                texto_secretario = (
                    f"{LEMBRETE_SECRETARIO_TITULO}\n\n"
                    + LEMBRETE_SECRETARIO_CORPO.format(
                        nome=nome_secretario,
                        data=data_evento,
                        loja=nome_loja,
                        horario=horario,
                        local=local,
                        grau=grau,
                        traje=traje,
                        agape=agape,
                        num_confirmados=num_confirmados,
                    )
                )

                try:
                    await bot.send_message(
                        chat_id=secretario_id,
                        text=texto_secretario,
                        parse_mode="Markdown"
                    )
                    print(f"Lembrete 24h enviado para secretário {nome_secretario} ({secretario_id})")
                except Exception as e:
                    print(f"Erro ao enviar lembrete 24h para secretário {secretario_id}: {e}")
        elif evento.get("Telegram ID do secretário", ""):
            logger.warning("Telegram ID do secretário inválido em lembrete 24h: %r", evento.get("Telegram ID do secretário", ""))


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

    eventos = listar_eventos()

    for evento in eventos:
        data_evento = str(evento.get("Data do evento", "") or "").strip()
        if not _mesmo_dia(data_evento, hoje):
            continue

        # Gera ID do evento (preferencialmente da coluna ID Evento, fallback para compatibilidade)
        id_evento = str(evento.get("ID Evento", "")).strip() or (data_evento + " — " + evento.get("Nome da loja", ""))
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
                + LEMBRETE_MEIO_DIA_CORPO.format(
                    nome=nome,
                    loja=nome_loja,
                    numero=numero_fmt,
                    local=local,
                    horario=horario,
                )
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
        secretario_id = _parse_telegram_id(evento.get("Telegram ID do secretário", ""))
        if secretario_id:
            secretario = buscar_membro(secretario_id)
            if secretario:
                nome_secretario = secretario.get("Nome", "")
                num_confirmados = len(confirmados)
                
                texto_secretario = (
                    f"{LEMBRETE_SECRETARIO_MEIO_DIA_TITULO}\n\n"
                    + LEMBRETE_SECRETARIO_MEIO_DIA_CORPO.format(
                        nome=nome_secretario,
                        loja=nome_loja,
                        numero=numero_fmt,
                        local=local,
                        horario=horario,
                        num_confirmados=num_confirmados,
                    )
                )

                try:
                    await bot.send_message(
                        chat_id=secretario_id,
                        text=texto_secretario,
                        parse_mode="Markdown"
                    )
                    print(f"Lembrete meio-dia enviado para secretário {nome_secretario} ({secretario_id})")
                except Exception as e:
                    print(f"Erro ao enviar lembrete meio-dia para secretário {secretario_id}: {e}")
        elif evento.get("Telegram ID do secretário", ""):
            logger.warning("Telegram ID do secretário inválido em lembrete meio-dia: %r", evento.get("Telegram ID do secretário", ""))


async def enviar_celebracao_mensal(bot: Bot):
    """Envia mensagem coletiva de celebração com estatísticas do mês anterior."""
    try:
        hoje = datetime.now()
        primeiro_dia_mes_atual = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
        primeiro_dia_mes_anterior = ultimo_dia_mes_anterior.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        data_inicio_str = primeiro_dia_mes_anterior.strftime("%d/%m/%Y")
        data_fim_str = ultimo_dia_mes_anterior.strftime("%d/%m/%Y")

        meses_pt = {
            1: "Janeiro",
            2: "Fevereiro",
            3: "Março",
            4: "Abril",
            5: "Maio",
            6: "Junho",
            7: "Julho",
            8: "Agosto",
            9: "Setembro",
            10: "Outubro",
            11: "Novembro",
            12: "Dezembro",
        }
        mes_referencia = meses_pt.get(primeiro_dia_mes_anterior.month, primeiro_dia_mes_anterior.strftime("%m/%Y"))

        confirmacoes_mes_anterior = await buscar_confirmacoes_no_periodo(data_inicio_str, data_fim_str)
        eventos_mes_anterior = await buscar_eventos_no_periodo(data_inicio_str, data_fim_str)

        total_visitas = len(confirmacoes_mes_anterior)
        lojas_diferentes = {
            str(evento.get("Nome da loja", "")).strip()
            for evento in eventos_mes_anterior
            if str(evento.get("Nome da loja", "")).strip()
        }
        total_lojas_diferentes = len(lojas_diferentes)

        if total_visitas <= 0:
            logger.info(
                "Nenhuma visita registrada no mês de %s. Mensagem de celebração não enviada.",
                mes_referencia,
            )
            return

        texto_celebracao = TEXTO_CELEBRACAO_MENSAL.format(
            mes_referencia=mes_referencia,
            total_visitas=total_visitas,
            total_lojas_diferentes=total_lojas_diferentes,
        )

        grupo_principal_id = getenv("GRUPO_PRINCIPAL_ID", "-1003721338228")
        await bot.send_message(
            chat_id=grupo_principal_id,
            text=texto_celebracao,
            parse_mode="Markdown",
        )

        logger.info("Mensagem de celebração mensal enviada para o grupo %s.", grupo_principal_id)
    except Exception as e:
        logger.error("Erro ao enviar celebração mensal: %s", e, exc_info=True)