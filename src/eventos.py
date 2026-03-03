# src/eventos.py
from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
)

from src.sheets import (
    listar_eventos,
    buscar_membro,
    registrar_confirmacao,
    cancelar_confirmacao,
    buscar_confirmacao,
    listar_confirmacoes_por_evento,
)

logger = logging.getLogger(__name__)

# -------------------------
# Constantes / helpers
# -------------------------

DIAS_SEMANA = {
    "Monday": "Segunda-feira",
    "Tuesday": "Terça-feira",
    "Wednesday": "Quarta-feira",
    "Thursday": "Quinta-feira",
    "Friday": "Sexta-feira",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}


def traduzir_dia(dia_ingles: str) -> str:
    return DIAS_SEMANA.get(dia_ingles, dia_ingles)


def traduzir_dia_abreviado(dia_ingles: str) -> str:
    dias_abreviados = {
        "Monday": "Segunda",
        "Tuesday": "Terça",
        "Wednesday": "Quarta",
        "Thursday": "Quinta",
        "Friday": "Sexta",
        "Saturday": "Sábado",
        "Sunday": "Domingo",
    }
    return dias_abreviados.get(dia_ingles, dia_ingles)


def extrair_tipo_agape(texto_agape: str) -> str:
    texto = (texto_agape or "").lower()
    if "pago" in texto or "dividido" in texto:
        return "pago"
    if "gratuito" in texto:
        return "gratuito"
    return "sem"


def parse_data_evento(texto: str) -> Optional[datetime]:
    """
    Aceita os formatos observados na planilha:
      - dd/mm/aaaa
      - yyyy-mm-dd HH:MM:SS
    """
    if not texto:
        return None
    texto = str(texto).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(texto, fmt)
        except Exception:
            pass
    return None


def normalizar_id_evento(ev: dict) -> str:
    """
    Chave do evento (retrocompatível):
      - Preferência: coluna 'ID Evento' (planilha v2)
      - Fallback: legado "Data do evento — Nome da loja"
    """
    id_planilha = str(ev.get("ID Evento", "")).strip()
    if id_planilha and id_planilha.lower() != "nan":
        return id_planilha
    return f"{ev.get('Data do evento', '')} — {ev.get('Nome da loja', '')}"


def _encode_cb(value: str) -> str:
    """
    Encoda para callback_data de forma retrocompatível.
    - Para IDs curtos (UUID hex, etc.), fica praticamente igual.
    - Para legado (com espaços/acentos), evita problemas de parsing.
    """
    return urllib.parse.quote(str(value), safe="")


def _decode_cb(value: str) -> str:
    return urllib.parse.unquote(value)


def montar_linha_confirmado(dados: dict) -> str:
    """
    Formato OFICIAL (1 confirmado por linha):
      {GrauNome} - {Nome} - {NomeDaLoja} {NumeroDaLoja} - {Oriente} - {Potencia}
    """
    grau = (dados.get("Grau") or "").strip()
    nome = (dados.get("Nome") or "").strip()
    loja = (dados.get("Loja") or "").strip()
    numero = (dados.get("Número da loja") or "").strip()
    oriente = (dados.get("Oriente") or "").strip()
    potencia = (dados.get("Potência") or "").strip()

    loja_composta = f"{loja} {numero}".strip()
    return f"{grau} - {nome} - {loja_composta} - {oriente} - {potencia}"


def _tid_to_int(value) -> Optional[int]:
    """
    Converte Telegram ID vindo de planilha (int/float/str/"123.0") para int.
    Retorna None se inválido.
    """
    if value is None:
        return None
    try:
        s = str(value).strip()
        if not s or s.lower() == "nan":
            return None
        return int(float(s))
    except Exception:
        return None


# -------------------------
# Fluxo: ver eventos
# -------------------------

async def mostrar_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    eventos = listar_eventos()
    if not eventos:
        await query.edit_message_text("Não há eventos ativos no momento. Volte em breve, irmão.")
        return

    # Agrupa por "Data do evento" (valor bruto) para manter compatibilidade
    eventos_por_data: dict[str, list[dict]] = {}
    for evento in eventos:
        data = str(evento.get("Data do evento", "")).strip()
        eventos_por_data.setdefault(data, []).append(evento)

    botoes = []
    for data, evs in eventos_por_data.items():
        data_obj = parse_data_evento(data)
        if data_obj:
            dia_semana = traduzir_dia_abreviado(data_obj.strftime("%A"))
            data_formatada = f"{data_obj.strftime('%d/%m')} ({dia_semana})"
        else:
            data_formatada = data

        botoes.append(
            [InlineKeyboardButton(
                f"📅 {data_formatada} - {len(evs)} evento(s)",
                callback_data=f"data|{_encode_cb(data)}"
            )]
        )

    if update.effective_chat.type == "private":
        botoes.append([InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")])
    else:
        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_grupo")])

    await query.edit_message_text(
        "Selecione uma data para ver os eventos:",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def mostrar_eventos_por_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, data_cod = query.data.split("|", 1)
    data = _decode_cb(data_cod)

    eventos = listar_eventos()
    eventos_data = [e for e in eventos if str(e.get("Data do evento", "")).strip() == str(data).strip()]

    if not eventos_data:
        await query.edit_message_text("Nenhum evento encontrado para esta data.")
        return

    graus: dict[str, list[dict]] = {}
    for evento in eventos_data:
        grau = evento.get("Grau", "Indefinido")
        graus.setdefault(grau, []).append(evento)

    botoes = []
    for grau, evs in graus.items():
        botoes.append(
            [InlineKeyboardButton(
                f"🔺 {grau} - {len(evs)} evento(s)",
                callback_data=f"grau|{_encode_cb(data)}|{_encode_cb(grau)}"
            )]
        )

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")])

    try:
        await query.edit_message_text(
            f"📅 *{data}*\n\nSelecione o grau:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botoes),
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Erro ao editar mensagem: {e}")


async def mostrar_eventos_por_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, data_cod, grau_cod = query.data.split("|", 2)
    data = _decode_cb(data_cod)
    grau = _decode_cb(grau_cod)

    eventos = listar_eventos()
    eventos_filtrados = [
        e for e in eventos
        if str(e.get("Data do evento", "")).strip() == str(data).strip()
        and str(e.get("Grau", "")).strip() == str(grau).strip()
    ]

    if not eventos_filtrados:
        await query.edit_message_text("Nenhum evento encontrado.")
        return

    botoes = []
    for evento in eventos_filtrados:
        nome = evento.get("Nome da loja", "Evento")
        numero = evento.get("Número da loja", "")
        potencia = evento.get("Potência", "")
        horario = evento.get("Hora", "")

        id_evento = normalizar_id_evento(evento)
        botoes.append(
            [InlineKeyboardButton(
                f"🏛 {nome} {numero} - {potencia} - {horario}",
                callback_data=f"evento|{_encode_cb(id_evento)}",
            )]
        )

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"data|{_encode_cb(data)}")])

    try:
        await query.edit_message_text(
            f"📅 *{data} - {grau}*\n\nSelecione o evento:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botoes),
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Erro ao editar mensagem: {e}")


async def mostrar_detalhes_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos()
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        await query.edit_message_text("Evento não encontrado.")
        return

    context.user_data["evento_atual"] = evento

    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")
    numero_loja = evento.get("Número da loja", "")
    horario = evento.get("Hora", "")
    endereco = evento.get("Endereço da sessão", "")
    grau = evento.get("Grau", "")
    tipo = evento.get("Tipo de sessão", "")
    rito = evento.get("Rito", "")
    potencia = evento.get("Potência", "")
    traje = evento.get("Traje obrigatório", "")
    agape = evento.get("Ágape", "")
    obs = evento.get("Observações", "")
    oriente = evento.get("Oriente", "")
    dia_semana_ingles = evento.get("Dia da semana", "")

    dia_semana = traduzir_dia(dia_semana_ingles)

    texto = (
        f"📅 *{data} — {nome_loja} {numero_loja}*\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"📍 Oriente: {oriente}\n"
        f"⚜️ Potência: {potencia}\n"
        f"📆 Dia: {dia_semana}\n"
        f"🕕 Horário: {horario if horario else 'Não informado'}\n"
        f"📍 Endereço: {endereco}\n"
        f"🔷 Grau mínimo: {grau}\n"
        f"📋 Tipo: {tipo}\n"
        f"✡️ Rito: {rito}\n"
        f"👔 Traje: {traje}\n"
        f"🍽️ Ágape: {agape}\n"
    )

    if obs and str(obs).strip().lower() not in ["n/a", "n", "nao", "não"]:
        texto += f"\n📌 Obs: {obs}"
    else:
        texto += "\n📌 Obs: Sem observações"

    telegram_id = update.effective_user.id
    ja_confirmou = buscar_confirmacao(id_evento, telegram_id)

    tipo_agape = extrair_tipo_agape(agape)
    botoes = []

    if ja_confirmou:
        botoes.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])
    else:
        if tipo_agape == "gratuito":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar|{_encode_cb(id_evento)}|gratuito")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{_encode_cb(id_evento)}|sem")])
        elif tipo_agape == "pago":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar|{_encode_cb(id_evento)}|pago")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{_encode_cb(id_evento)}|sem")])
        else:
            botoes.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{_encode_cb(id_evento)}|sem")])

    botoes.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")])

    teclado = InlineKeyboardMarkup(botoes)

    # No grupo: manda uma nova mensagem (não edita a mensagem do botão, para não “estragar” o card/menu)
    if update.effective_chat.type in ["group", "supergroup"]:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texto,
            parse_mode="Markdown",
            reply_markup=teclado,
        )
    else:
        try:
            await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Erro ao editar mensagem: {e}")


# -------------------------
# Lista de confirmados (cortina + fechar)
# -------------------------

async def ver_confirmados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos()
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        # Em grupo, pode ser melhor responder sem editar a mensagem original
        if update.effective_chat.type in ["group", "supergroup"]:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Evento não encontrado.")
        else:
            await query.edit_message_text("Evento não encontrado.")
        return

    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")

    confirmacoes = listar_confirmacoes_por_evento(id_evento)

    if not confirmacoes:
        texto = (
            f"👥 *CONFIRMADOS - {nome_loja}*\n"
            f"📅 {data}\n\n"
            f"Nenhum irmão confirmou presença ainda."
        )
    else:
        texto = (
            f"👥 *CONFIRMADOS - {nome_loja}*\n"
            f"📅 {data}\n\n"
            f"Total: {len(confirmacoes)} irmão(s)\n\n"
        )

        linhas = []
        for conf in confirmacoes:
            tid = _tid_to_int(conf.get("Telegram ID"))
            membro = buscar_membro(tid) if tid is not None else None

            # Preferir cadastro atual do membro; fallback para snapshot na confirmação
            dados = membro if membro else conf
            linhas.append(montar_linha_confirmado(dados))

        for linha in sorted(linhas, key=lambda x: x.lower()):
            texto += linha + "\n"

    # Botões da cortina
    user_id = update.effective_user.id
    user_confirmado = any(str(conf.get("Telegram ID")) == str(user_id) for conf in confirmacoes)

    botoes = []
    if user_confirmado:
        botoes.append([InlineKeyboardButton("❌ Cancelar minha presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")])

    botoes.append([InlineKeyboardButton("🔒 Fechar", callback_data="fechar_mensagem")])

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def fechar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        if query.message:
            await query.message.delete()
    except Exception as e:
        # Em alguns casos o bot não tem permissão pra deletar no grupo
        logger.error(f"Erro ao fechar mensagem (delete): {e}")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass


# -------------------------
# Minhas confirmações (privado)
# -------------------------

async def minhas_confirmacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    eventos = listar_eventos()

    confirmados = []
    for evento in eventos:
        id_evento = normalizar_id_evento(evento)
        if buscar_confirmacao(id_evento, user_id):
            confirmados.append(evento)

    if not confirmados:
        botoes = [[InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")]]
        await query.edit_message_text(
            "Você não tem confirmações ativas no momento.",
            reply_markup=InlineKeyboardMarkup(botoes),
        )
        return

    botoes = []
    for evento in confirmados:
        data = str(evento.get("Data do evento", "")).strip()
        grau = str(evento.get("Grau", "")).strip()
        nome = str(evento.get("Nome da loja", "")).strip()
        numero = str(evento.get("Número da loja", "")).strip()
        potencia = str(evento.get("Potência", "")).strip()
        horario = str(evento.get("Hora", "")).strip()

        data_obj = parse_data_evento(data)
        if data_obj:
            data_curta = data_obj.strftime("%d/%m")
        else:
            data_curta = data[:5] if len(data) >= 5 else data

        texto_botao = f"{data_curta} — {grau} — {nome} {numero} ({potencia}) às {horario}"

        id_evento = normalizar_id_evento(evento)
        botoes.append(
            [InlineKeyboardButton(texto_botao, callback_data=f"detalhes_confirmado|{_encode_cb(id_evento)}")]
        )

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")])

    await query.edit_message_text(
        "*📋 Selecione uma sessão para ver detalhes:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def detalhes_confirmado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, id_evento_cod = query.data.split("|", 1)
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos()
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        await query.edit_message_text("Evento não encontrado.")
        return

    user_id = update.effective_user.id
    confirmacao = buscar_confirmacao(id_evento, user_id)
    if not confirmacao:
        await query.edit_message_text("Você não está mais confirmado neste evento.")
        return

    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")
    numero_loja = evento.get("Número da loja", "")
    horario = evento.get("Hora", "")
    endereco = evento.get("Endereço da sessão", "")
    grau = evento.get("Grau", "")
    tipo = evento.get("Tipo de sessão", "")
    rito = evento.get("Rito", "")
    potencia = evento.get("Potência", "")
    traje = evento.get("Traje obrigatório", "")
    agape = evento.get("Ágape", "")
    obs = evento.get("Observações", "")
    oriente = evento.get("Oriente", "")
    dia_semana_ingles = evento.get("Dia da semana", "")
    dia_semana = traduzir_dia(dia_semana_ingles)
    participacao_agape = confirmacao.get("Ágape", "Não informado")

    texto = (
        f"📅 *{data} — {nome_loja} {numero_loja}*\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"📍 Oriente: {oriente}\n"
        f"⚜️ Potência: {potencia}\n"
        f"📆 Dia: {dia_semana}\n"
        f"🕕 Horário: {horario}\n"
        f"📍 Endereço: {endereco}\n"
        f"🔷 Grau mínimo: {grau}\n"
        f"📋 Tipo: {tipo}\n"
        f"✡️ Rito: {rito}\n"
        f"👔 Traje: {traje}\n"
        f"🍽️ Ágape: {agape}\n\n"
        f"*Sua confirmação:*\n"
        f"🍽 Participação no ágape: {participacao_agape}\n"
    )

    if obs and str(obs).strip().lower() not in ["n/a", "n", "nao", "não"]:
        texto += f"\n📌 Obs: {obs}"

    botoes = [
        [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{_encode_cb(id_evento)}")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes")],
    ]

    try:
        await query.edit_message_text(
            texto,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botoes),
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Erro ao editar mensagem: {e}")


# -------------------------
# Confirmação de presença
# -------------------------

async def iniciar_confirmacao_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    partes = query.data.split("|")
    if len(partes) != 3:
        await query.edit_message_text("Erro: dados de confirmação inválidos.")
        return ConversationHandler.END

    _, id_evento_cod, tipo_agape = partes
    id_evento = _decode_cb(id_evento_cod)

    eventos = listar_eventos()
    evento = next((ev for ev in eventos if normalizar_id_evento(ev) == id_evento), None)
    if not evento:
        await query.edit_message_text("Evento não encontrado. Pode ter sido cancelado.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    if not membro:
        context.user_data["pos_cadastro"] = {
            "acao": "confirmar",
            "id_evento": id_evento,
            "tipo_agape": tipo_agape,
        }
        botoes_cadastro = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📝 Iniciar cadastro", callback_data="iniciar_cadastro")],
                [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_grupo")],
            ]
        )

        if update.effective_chat.type in ["group", "supergroup"]:
            await query.edit_message_text(
                "🔔 Você precisa se cadastrar primeiro!\n\n"
                "Clique no botão abaixo para iniciar seu cadastro no privado.",
                reply_markup=botoes_cadastro,
            )
        else:
            await query.edit_message_text(
                "Olá! Antes de confirmar sua presença, preciso fazer seu cadastro.\n\n"
                "Clique no botão abaixo para começar:",
                reply_markup=botoes_cadastro,
            )
        return ConversationHandler.END

    ja_confirmou = buscar_confirmacao(id_evento, user_id)
    if ja_confirmou:
        botoes_confirmado = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
                [InlineKeyboardButton("🔙 Manter confirmação", callback_data=f"evento|{_encode_cb(id_evento)}")],
            ]
        )
        await query.edit_message_text(
            "Você já confirmou presença para este evento.\n\n"
            "Deseja cancelar sua confirmação?",
            reply_markup=botoes_confirmado,
        )
        return ConversationHandler.END

    # Registrar confirmação (mantém snapshot, mas lista oficial busca dados atuais no cadastro)
    participacao_agape = "Confirmada" if tipo_agape != "sem" else "Não selecionada"
    if tipo_agape == "gratuito":
        desc_agape = "Gratuito"
    elif tipo_agape == "pago":
        desc_agape = "Pago"
    else:
        desc_agape = "Não aplicável"

    dados_confirmacao = {
        "id_evento": id_evento,
        "telegram_id": str(user_id),
        "nome": membro.get("Nome", ""),
        "grau": membro.get("Grau", ""),
        "cargo": membro.get("Cargo", ""),
        "loja": membro.get("Loja", ""),
        "numero_loja": membro.get("Número da loja", ""),
        "oriente": membro.get("Oriente", ""),
        "potencia": membro.get("Potência", ""),
        "agape": f"{participacao_agape} ({desc_agape})" if participacao_agape == "Confirmada" else "Não",
    }
    registrar_confirmacao(dados_confirmacao)

    # Mensagem no privado com resumo
    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")
    numero_loja = evento.get("Número da loja", "")
    horario = evento.get("Hora", "")
    potencia_evento = evento.get("Potência", "")
    dia_semana_ingles = evento.get("Dia da semana", "")
    dia_semana = traduzir_dia(dia_semana_ingles)

    resposta = f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
    resposta += "*Resumo da confirmação:*\n"
    resposta += f"📅 {data} — {nome_loja} {numero_loja}\n"
    resposta += f"⚜️ Potência: {potencia_evento}\n"
    resposta += f"📆 Dia: {dia_semana}\n"
    resposta += f"🕕 Horário: {horario}\n"
    resposta += f"🍽 Participação no ágape: {participacao_agape} ({desc_agape})\n\n"
    resposta += "Sua confirmação é muito importante! Ela nos ajuda a organizar tudo com carinho e evitar desperdícios.\n\n"
    resposta += "Fraterno abraço!"

    botoes_privado = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{_encode_cb(id_evento)}")],
            [InlineKeyboardButton("👥 Ver eventos", callback_data="ver_eventos")],
        ]
    )

    await context.bot.send_message(
        chat_id=user_id,
        text=resposta,
        parse_mode="Markdown",
        reply_markup=botoes_privado,
    )

    if update.effective_chat.type in ["group", "supergroup"]:
        await query.answer("Presença confirmada! Verifique seu privado.")
    else:
        await query.edit_message_text("✅ Presença confirmada! Verifique a mensagem acima.")

    return ConversationHandler.END


async def cancelar_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Confirmação de cancelamento (passo 2)
    if query.data.startswith("confirma_cancelar|"):
        _, id_evento_cod = query.data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id

        cancelou = cancelar_confirmacao(id_evento, user_id)
        if cancelou:
            await query.edit_message_text(
                "❌ Presença cancelada.\n\n"
                f"Evento: {id_evento}\n\n"
                "Se mudar de ideia, basta confirmar novamente. Fraterno abraço!"
            )
        else:
            await query.edit_message_text("Não foi possível cancelar. Você não estava confirmado para este evento.")
        return

    # Pedido de cancelamento (passo 1)
    if query.data.startswith("cancelar|"):
        _, id_evento_cod = query.data.split("|", 1)
        id_evento = _decode_cb(id_evento_cod)
        user_id = update.effective_user.id

        if update.effective_chat.type in ["group", "supergroup"]:
            botoes = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Sim, cancelar", callback_data=f"confirma_cancelar|{_encode_cb(id_evento)}")],
                    [InlineKeyboardButton("🔙 Não, voltar", callback_data=f"evento|{_encode_cb(id_evento)}")],
                ]
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Confirmar cancelamento da sessão {id_evento}?",
                reply_markup=botoes,
            )
            await query.edit_message_text("Instruções enviadas no privado.")
            return

        cancelou = cancelar_confirmacao(id_evento, user_id)
        if cancelou:
            await query.edit_message_text(
                "❌ Presença cancelada.\n\n"
                f"Evento: {id_evento}\n\n"
                "Se mudar de ideia, basta confirmar novamente. Fraterno abraço!"
            )
        else:
            await query.edit_message_text("Não foi possível cancelar. Você não estava confirmado para este evento.")
        return

    await query.edit_message_text("Comando de cancelamento inválido.")


# -------------------------
# Handlers (para importar no bot.py)
# -------------------------

confirmacao_presenca_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_confirmacao_presenca, pattern=r"^confirmar\|")],
    states={},
    fallbacks=[CommandHandler("cancelar", cancelar_presenca)],
)

EVENTOS_HANDLERS = [
    CallbackQueryHandler(mostrar_eventos, pattern=r"^ver_eventos$"),
    CallbackQueryHandler(mostrar_eventos_por_data, pattern=r"^data\|"),
    CallbackQueryHandler(mostrar_eventos_por_grau, pattern=r"^grau\|"),
    CallbackQueryHandler(mostrar_detalhes_evento, pattern=r"^evento\|"),
    CallbackQueryHandler(ver_confirmados, pattern=r"^ver_confirmados\|"),
    CallbackQueryHandler(minhas_confirmacoes, pattern=r"^minhas_confirmacoes$"),
    CallbackQueryHandler(detalhes_confirmado, pattern=r"^detalhes_confirmado\|"),
    CallbackQueryHandler(cancelar_presenca, pattern=r"^(cancelar\||confirma_cancelar\|)"),
    CallbackQueryHandler(fechar_mensagem, pattern=r"^fechar_mensagem$"),
]