# src/eventos.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, CommandHandler
from src.sheets import (
    listar_eventos, buscar_membro, registrar_confirmacao,
    cancelar_confirmacao, buscar_confirmacao, listar_confirmacoes_por_evento
)
from datetime import datetime
import re
import urllib.parse
import logging

logger = logging.getLogger(__name__)

# Dicionário para traduzir dias da semana para português
DIAS_SEMANA = {
    "Monday": "Segunda-feira",
    "Tuesday": "Terça-feira",
    "Wednesday": "Quarta-feira",
    "Thursday": "Quinta-feira",
    "Friday": "Sexta-feira",
    "Saturday": "Sábado",
    "Sunday": "Domingo"
}

AGAPE_CHOICE = range(1)

def traduzir_dia(dia_ingles):
    return DIAS_SEMANA.get(dia_ingles, dia_ingles)

def traduzir_dia_abreviado(dia_ingles):
    dias_abreviados = {
        "Monday": "Segunda",
        "Tuesday": "Terça",
        "Wednesday": "Quarta",
        "Thursday": "Quinta",
        "Friday": "Sexta",
        "Saturday": "Sábado",
        "Sunday": "Domingo"
    }
    return dias_abreviados.get(dia_ingles, dia_ingles)

def extrair_tipo_agape(texto_agape):
    texto = texto_agape.lower()
    if "pago" in texto or "dividido" in texto:
        return "pago"
    elif "gratuito" in texto:
        return "gratuito"
    else:
        return "sem"

async def mostrar_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    eventos = listar_eventos()
    if not eventos:
        await query.edit_message_text("Não há eventos ativos no momento. Volte em breve, irmão.")
        return

    eventos_por_data = {}
    for i, evento in enumerate(eventos):
        data = evento.get("Data do evento", "")
        if data not in eventos_por_data:
            eventos_por_data[data] = []
        eventos_por_data[data].append((i, evento))

    botoes = []
    for data, evs in eventos_por_data.items():
        try:
            data_obj = datetime.strptime(data, "%d/%m/%Y")
            dia_semana = traduzir_dia_abreviado(data_obj.strftime("%A"))
            data_formatada = f"{data_obj.strftime('%d/%m')} ({dia_semana})"
        except:
            data_formatada = data
        botoes.append([InlineKeyboardButton(
            f"📅 {data_formatada} - {len(evs)} evento(s)",
            callback_data=f"data|{data}"
        )])

    from src.permissoes import get_nivel
    nivel = get_nivel(update.effective_user.id)

    botoes_voltar = []
    if update.effective_chat.type == "private":
        botoes_voltar = [[InlineKeyboardButton("⬅️ Voltar ao menu", callback_data="menu_principal")]]
    else:
        botoes_voltar = [[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_grupo")]]

    teclado = InlineKeyboardMarkup(botoes + botoes_voltar)
    await query.edit_message_text("Selecione uma data para ver os eventos:", reply_markup=teclado)

async def mostrar_eventos_por_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, data = query.data.split("|", 1)
    eventos = listar_eventos()
    eventos_data = [e for e in eventos if e.get("Data do evento") == data]

    if not eventos_data:
        await query.edit_message_text("Nenhum evento encontrado para esta data.")
        return

    graus = {}
    for evento in eventos_data:
        grau = evento.get("Grau", "Indefinido")
        if grau not in graus:
            graus[grau] = []
        graus[grau].append(evento)

    botoes = []
    for grau, evs in graus.items():
        botoes.append([InlineKeyboardButton(
            f"🔺 {grau} - {len(evs)} evento(s)",
            callback_data=f"grau|{data}|{grau}"
        )])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")])
    teclado = InlineKeyboardMarkup(botoes)

    try:
        await query.edit_message_text(
            f"📅 *{data}*\n\nSelecione o grau:",
            parse_mode="Markdown",
            reply_markup=teclado
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Erro ao editar mensagem: {e}")

async def mostrar_eventos_por_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, data, grau = query.data.split("|", 2)
    eventos = listar_eventos()
    eventos_filtrados = [
        e for e in eventos
        if e.get("Data do evento") == data and e.get("Grau") == grau
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
        id_evento = f"{evento.get('Data do evento')} — {evento.get('Nome da loja')}"
        id_evento_codificado = urllib.parse.quote(id_evento, safe='')
        botoes.append([InlineKeyboardButton(
            f"🏛 {nome} {numero} - {potencia} - {horario}",
            callback_data=f"evento|{id_evento_codificado}"
        )])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"data|{data}")])
    teclado = InlineKeyboardMarkup(botoes)

    try:
        await query.edit_message_text(
            f"📅 *{data} - {grau}*\n\nSelecione o evento:",
            parse_mode="Markdown",
            reply_markup=teclado
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Erro ao editar mensagem: {e}")

async def mostrar_detalhes_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, id_evento_codificado = query.data.split("|", 1)
    id_evento = urllib.parse.unquote(id_evento_codificado)

    eventos = listar_eventos()
    evento = None
    for ev in eventos:
        if (ev.get("Data do evento", "") + " — " + ev.get("Nome da loja", "")) == id_evento:
            evento = ev
            break

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

    if obs and obs.strip().lower() not in ["n/a", "n", "nao", "não"]:
        texto += f"\n📌 Obs: {obs}"
    else:
        texto += "\n📌 Obs: Sem observações"

    telegram_id = update.effective_user.id
    ja_confirmou = buscar_confirmacao(id_evento, telegram_id)

    tipo_agape = extrair_tipo_agape(agape)
    botoes = []

    if ja_confirmou:
        botoes.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{id_evento_codificado}")])
    else:
        if tipo_agape == "gratuito":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar|{id_evento_codificado}|gratuito")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento_codificado}|sem")])
        elif tipo_agape == "pago":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar|{id_evento_codificado}|pago")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento_codificado}|sem")])
        else:
            botoes.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_evento_codificado}|sem")])

    botoes.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{id_evento_codificado}")])

    teclado = InlineKeyboardMarkup(botoes)

    if update.effective_chat.type in ["group", "supergroup"]:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texto,
            parse_mode="Markdown",
            reply_markup=teclado
        )
    else:
        try:
            await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Erro ao editar mensagem: {e}")

async def ver_confirmados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, id_evento_codificado = query.data.split("|", 1)
    id_evento = urllib.parse.unquote(id_evento_codificado)

    eventos = listar_eventos()
    evento = None
    for ev in eventos:
        if (ev.get("Data do evento", "") + " — " + ev.get("Nome da loja", "")) == id_evento:
            evento = ev
            break

    if not evento:
        await query.edit_message_text("Evento não encontrado.")
        return

    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")

    confirmacoes = listar_confirmacoes_por_evento(id_evento)

    if not confirmacoes:
        texto = f"👥 *CONFIRMADOS - {nome_loja}*\n📅 {data}\n\nNenhum irmão confirmou presença ainda.\n\nSeja o primeiro! 🐐"
    else:
        texto = f"👥 *CONFIRMADOS - {nome_loja}*\n📅 {data}\n\nTotal: {len(confirmacoes)} irmão(s)\n\n"
        for conf in confirmacoes:
            nome = conf.get("Nome", "Desconhecido")
            grau = conf.get("Grau", "")
            loja = conf.get("Loja", "")
            numero = conf.get("Número da loja", "")
            oriente = conf.get("Oriente", "")
            potencia = conf.get("Potência", "")
            agape = conf.get("Ágape", "")
            linha = f"• {nome}, {grau}, {loja} {numero}, {oriente}, {potencia}"
            if "Confirmada" in str(agape) or "Sim" in str(agape):
                linha += " - 🍽 Com ágape"
            else:
                linha += " - 🚫 Sem ágape"
            texto += linha + "\n"

    user_id = update.effective_user.id
    user_confirmado = any(str(conf.get("Telegram ID")) == str(user_id) for conf in confirmacoes)

    botoes = []
    if user_confirmado:
        botoes.append([InlineKeyboardButton("❌ Cancelar minha presença", callback_data=f"cancelar|{id_evento_codificado}")])
    else:
        tipo_agape = extrair_tipo_agape(evento.get("Ágape", ""))
        if tipo_agape == "gratuito":
            botoes.append([InlineKeyboardButton("🍽 Confirmar com ágape (gratuito)", callback_data=f"confirmar|{id_evento_codificado}|gratuito")])
            botoes.append([InlineKeyboardButton("🚫 Confirmar sem ágape", callback_data=f"confirmar|{id_evento_codificado}|sem")])
        elif tipo_agape == "pago":
            botoes.append([InlineKeyboardButton("🍽 Confirmar com ágape (pago)", callback_data=f"confirmar|{id_evento_codificado}|pago")])
            botoes.append([InlineKeyboardButton("🚫 Confirmar sem ágape", callback_data=f"confirmar|{id_evento_codificado}|sem")])
        else:
            botoes.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_evento_codificado}|sem")])

    botoes.append([InlineKeyboardButton("🔒 Fechar", callback_data="fechar_mensagem")])
    teclado = InlineKeyboardMarkup(botoes)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texto,
        parse_mode="Markdown",
        reply_markup=teclado
    )

async def fechar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.delete_message()
    except:
        await query.edit_message_text("Mensagem fechada.")

async def minhas_confirmacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    eventos = listar_eventos()

    confirmados = []
    for evento in eventos:
        id_evento = evento.get("Data do evento", "") + " — " + evento.get("Nome da loja", "")
        if buscar_confirmacao(id_evento, user_id):
            confirmados.append(evento)

    if not confirmados:
        await query.edit_message_text(
            "Você não tem nenhuma presença confirmada no momento.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 Ver eventos", callback_data="ver_eventos")
            ]])
        )
        return

    botoes = []
    for idx, evento in enumerate(confirmados):
        data = evento.get("Data do evento", "")
        grau = evento.get("Grau", "")
        nome = evento.get("Nome da loja", "")
        numero = evento.get("Número da loja", "")
        potencia = evento.get("Potência", "")
        horario = evento.get("Hora", "")
        data_curta = data[0:5] if len(data) >= 5 else data
        texto_botao = f"{data_curta} — {grau} — {nome} {numero} ({potencia}) às {horario}"
        id_evento = f"{data} — {nome}"
        id_evento_codificado = urllib.parse.quote(id_evento, safe='')
        botoes.append([InlineKeyboardButton(
            texto_botao, 
            callback_data=f"detalhes_confirmado|{id_evento_codificado}"
        )])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")])
    await query.edit_message_text(
        "*📋 Selecione uma sessão para ver detalhes:*",
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(botoes)
    )

async def detalhes_confirmado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, id_evento_codificado = query.data.split("|", 1)
    id_evento = urllib.parse.unquote(id_evento_codificado)

    eventos = listar_eventos()
    evento = None
    for ev in eventos:
        if (ev.get("Data do evento", "") + " — " + ev.get("Nome da loja", "")) == id_evento:
            evento = ev
            break

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

    if obs and obs.strip().lower() not in ["n/a", "n", "nao", "não"]:
        texto += f"\n📌 Obs: {obs}"

    botoes = [
        [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{id_evento_codificado}")],
        [InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{id_evento_codificado}")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="minhas_confirmacoes")]
    ]

    try:
        await query.edit_message_text(
            texto, 
            parse_mode="Markdown", 
            reply_markup=InlineKeyboardMarkup(botoes)
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Erro ao editar mensagem: {e}")

async def iniciar_confirmacao_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    partes = query.data.split("|")
    if len(partes) != 3:
        await query.edit_message_text("Erro: dados de confirmação inválidos.")
        return ConversationHandler.END

    _, id_evento_codificado, tipo_agape = partes
    id_evento = urllib.parse.unquote(id_evento_codificado)

    eventos = listar_eventos()
    evento = None
    for ev in eventos:
        if (ev.get("Data do evento", "") + " — " + ev.get("Nome da loja", "")) == id_evento:
            evento = ev
            break

    if not evento:
        await query.edit_message_text("Evento não encontrado. Pode ter sido excluído.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    membro = buscar_membro(user_id)

    if not membro:
        context.user_data["pos_cadastro"] = {
            "acao": "confirmar",
            "id_evento": id_evento,
            "tipo_agape": tipo_agape
        }
        botoes_cadastro = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Iniciar cadastro", callback_data="iniciar_cadastro")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_grupo")]
        ])
        if update.effective_chat.type in ["group", "supergroup"]:
            await query.edit_message_text(
                "🔔 Você precisa se cadastrar primeiro!\n\n"
                "Clique no botão abaixo para iniciar seu cadastro no privado.",
                reply_markup=botoes_cadastro
            )
        else:
            await query.edit_message_text(
                "Olá! Antes de confirmar sua presença, preciso fazer seu cadastro.\n\n"
                "Clique no botão abaixo para começar:",
                reply_markup=botoes_cadastro
            )
        return ConversationHandler.END

    ja_confirmou = buscar_confirmacao(id_evento, user_id)
    if ja_confirmou:
        botoes_confirmado = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{id_evento_codificado}")],
            [InlineKeyboardButton("🔙 Manter confirmação", callback_data=f"evento|{id_evento_codificado}")]
        ])
        await query.edit_message_text(
            "Você já confirmou presença para este evento.\n\n"
            "Deseja cancelar sua confirmação?",
            reply_markup=botoes_confirmado
        )
        return ConversationHandler.END

    # Registrar confirmação
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

    # Enviar mensagem de confirmação no privado
    data = evento.get("Data do evento", "")
    nome_loja = evento.get("Nome da loja", "")
    numero_loja = evento.get("Número da loja", "")
    horario = evento.get("Hora", "")
    potencia_evento = evento.get("Potência", "")
    dia_semana_ingles = evento.get("Dia da semana", "")
    dia_semana = traduzir_dia(dia_semana_ingles)

    resposta = f"✅ Presença confirmada, irmão {membro.get('Nome', '')}!\n\n"
    resposta += f"*Resumo da confirmação:*\n"
    resposta += f"📅 {data} — {nome_loja} {numero_loja}\n"
    resposta += f"⚜️ Potência: {potencia_evento}\n"
    resposta += f"📆 Dia: {dia_semana}\n"
    resposta += f"🕕 Horário: {horario}\n"
    resposta += f"🍽 Participação no ágape: {participacao_agape} ({desc_agape})\n\n"
    resposta += "Sua confirmação é muito importante! Ela nos ajuda a organizar tudo com carinho e evitar desperdícios.\n\n"
    resposta += "Fraterno abraço! 🐐"

    botoes_privado = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{id_evento_codificado}")],
        [InlineKeyboardButton("👥 Ver eventos", callback_data="ver_eventos")]
    ])

    await context.bot.send_message(
        chat_id=user_id,
        text=resposta,
        parse_mode="Markdown",
        reply_markup=botoes_privado
    )

    if update.effective_chat.type in ["group", "supergroup"]:
        await query.answer("Presença confirmada! Verifique seu privado.")
    else:
        await query.edit_message_text("✅ Presença confirmada! Verifique a mensagem acima.")

    return ConversationHandler.END

async def cancelar_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("confirma_cancelar|"):
        _, id_evento_codificado = query.data.split("|", 1)
        id_evento = urllib.parse.unquote(id_evento_codificado)
        user_id = update.effective_user.id

        cancelou = cancelar_confirmacao(id_evento, user_id)
        if cancelou:
            await query.edit_message_text(
                f"❌ Presença cancelada.\n\n"
                f"Evento: {id_evento}\n\n"
                f"Se mudar de ideia, basta confirmar novamente. Fraterno abraço! 🐐"
            )
        else:
            await query.edit_message_text("Não foi possível cancelar. Você não estava confirmado para este evento.")
        return

    elif query.data.startswith("cancelar|"):
        _, id_evento_codificado = query.data.split("|", 1)
        id_evento = urllib.parse.unquote(id_evento_codificado)
        user_id = update.effective_user.id

        if update.effective_chat.type in ["group", "supergroup"]:
            botoes = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sim, cancelar", callback_data=f"confirma_cancelar|{id_evento_codificado}")],
                [InlineKeyboardButton("🔙 Não, voltar", callback_data=f"evento|{id_evento_codificado}")]
            ])
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Confirmar cancelamento da sessão {id_evento}?",
                reply_markup=botoes
            )
            await query.edit_message_text("Instruções enviadas no privado.")
            return
        else:
            cancelou = cancelar_confirmacao(id_evento, user_id)
            if cancelou:
                await query.edit_message_text(
                    f"❌ Presença cancelada.\n\n"
                    f"Evento: {id_evento}\n\n"
                    f"Se mudar de ideia, basta confirmar novamente. Fraterno abraço! 🐐"
                )
            else:
                await query.edit_message_text("Não foi possível cancelar. Você não estava confirmado para este evento.")
        return

    else:
        await query.edit_message_text("Comando de cancelamento inválido.")

confirmacao_presenca_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_confirmacao_presenca, pattern="^confirmar\\|")],
    states={},
    fallbacks=[CommandHandler("cancelar", cancelar_presenca)],
)