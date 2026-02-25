# src/eventos.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, CommandHandler
from src.sheets import (
    listar_eventos, buscar_membro, registrar_confirmacao,
    cancelar_confirmacao, buscar_confirmacao, listar_confirmacoes_por_evento
)
from datetime import datetime
import re

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
    """Traduz o dia da semana para português."""
    return DIAS_SEMANA.get(dia_ingles, dia_ingles)

def extrair_tipo_agape(texto_agape):
    """Extrai o tipo de ágape do texto da planilha."""
    texto = texto_agape.lower()
    if "pago" in texto or "dividido" in texto:
        return "pago"
    elif "gratuito" in texto:
        return "gratuito"
    else:
        return "sem"

async def mostrar_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista eventos disponíveis para seleção, agrupados por data."""
    query = update.callback_query
    await query.answer()

    eventos = listar_eventos()
    if not eventos:
        await query.edit_message_text("Não há eventos ativos no momento. Volte em breve, irmão.")
        return

    # Agrupar por data
    eventos_por_data = {}
    for i, evento in enumerate(eventos):
        data = evento.get("Data do evento", "")
        if data not in eventos_por_data:
            eventos_por_data[data] = []
        eventos_por_data[data].append((i, evento))

    # Criar botões por data
    botoes = []
    for data, evs in eventos_por_data.items():
        try:
            data_obj = datetime.strptime(data, "%d/%m/%Y")
            dia_semana = traduzir_dia(data_obj.strftime("%A"))
            data_formatada = f"{data_obj.strftime('%d/%m')} ({dia_semana[:3]})"
        except:
            data_formatada = data
        botoes.append([InlineKeyboardButton(
            f"📅 {data_formatada} - {len(evs)} evento(s)",
            callback_data=f"data|{data}"
        )])

    # Botão voltar
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
    """Mostra eventos de uma data específica, agrupados por grau."""
    query = update.callback_query
    await query.answer()

    _, data = query.data.split("|", 1)
    eventos = listar_eventos()
    eventos_data = [e for e in eventos if e.get("Data do evento") == data]

    if not eventos_data:
        await query.edit_message_text("Nenhum evento encontrado para esta data.")
        return

    # Agrupar por grau
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

    await query.edit_message_text(
        f"📅 *{data}*\n\nSelecione o grau:",
        parse_mode="Markdown",
        reply_markup=teclado
    )

async def mostrar_eventos_por_grau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista eventos de uma data e grau específicos."""
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
        # Criar identificador único baseado em data e nome da loja
        data_clean = evento.get("Data do evento", "").replace('/', '_')
        nome_clean = re.sub(r'[^a-zA-Z0-9]', '_', str(evento.get("Nome da loja", "")))
        numero_clean = re.sub(r'[^a-zA-Z0-9]', '_', str(evento.get("Número da loja", "")))  # CONVERTIDO PARA STRING
        evento_id = f"{data_clean}_{nome_clean}_{numero_clean}"

        nome = evento.get("Nome da loja", "Evento")
        numero = evento.get("Número da loja", "")
        potencia = evento.get("Potência", "")
        horario = evento.get("Hora", "")
        botoes.append([InlineKeyboardButton(
            f"🏛 {nome} {numero} - {potencia} - {horario}",
            callback_data=f"evento|{evento_id}"
        )])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"data|{data}")])
    teclado = InlineKeyboardMarkup(botoes)

    await query.edit_message_text(
        f"📅 *{data} - {grau}*\n\nSelecione o evento:",
        parse_mode="Markdown",
        reply_markup=teclado
    )

async def mostrar_detalhes_evento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra detalhes de um evento específico."""
    query = update.callback_query
    await query.answer()

    _, evento_id = query.data.split("|", 1)  # formato "evento|25_12_2026_Natalina_2512"

    # Reconstruir data e nome
    partes = evento_id.split("_")
    if len(partes) < 3:
        await query.edit_message_text("Erro: identificador do evento inválido.")
        return
    data_str = f"{partes[0]}/{partes[1]}/{partes[2]}"
    nome_loja = partes[3].replace('_', ' ') if len(partes) > 3 else ""

    eventos = listar_eventos()
    evento = None
    for ev in eventos:
        if ev.get("Data do evento") == data_str and ev.get("Nome da loja") == nome_loja:
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
    id_evento = f"{data} — {nome_loja}"
    ja_confirmou = buscar_confirmacao(id_evento, telegram_id)

    tipo_agape = extrair_tipo_agape(agape)
    botoes = []

    if ja_confirmou:
        botoes.append([InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{id_evento}")])
    else:
        if tipo_agape == "gratuito":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (gratuito)", callback_data=f"confirmar|{id_evento}|gratuito")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
        elif tipo_agape == "pago":
            botoes.append([InlineKeyboardButton("🍽 Participar com ágape (pago)", callback_data=f"confirmar|{id_evento}|pago")])
            botoes.append([InlineKeyboardButton("🚫 Participar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
        else:
            botoes.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_evento}|sem")])

    botoes.append([InlineKeyboardButton("👥 Ver confirmados", callback_data=f"ver_confirmados|{id_evento}")])

    if update.effective_chat.type == "private":
        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="ver_eventos")])
    else:
        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_grupo")])

    teclado = InlineKeyboardMarkup(botoes)

    if update.effective_chat.type in ["group", "supergroup"]:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texto,
            parse_mode="Markdown",
            reply_markup=teclado
        )
        try:
            await query.delete_message()
        except:
            pass
    else:
        await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)

async def ver_confirmados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra lista de confirmados em mensagem temporária."""
    query = update.callback_query
    await query.answer()

    _, id_evento = query.data.split("|", 1)  # formato "ver_confirmados|25/12/2026 — Natalina"

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
            oriente = conf.get("Oriente", "")
            potencia = conf.get("Potência", "")
            agape = conf.get("Ágape", "")
            if "Confirmada" in str(agape) or "Sim" in str(agape):
                icone = "🍽"
                status = "Com ágape"
            else:
                icone = "🚫"
                status = "Sem ágape"
            texto += f"• {grau} {nome} - {loja} ({oriente}) - {potencia} - {icone} {status}\n"

    # Botões da mensagem temporária
    user_id = update.effective_user.id
    user_confirmado = any(str(conf.get("Telegram ID")) == str(user_id) for conf in confirmacoes)

    botoes = []
    if user_confirmado:
        botoes.append([InlineKeyboardButton("❌ Cancelar minha presença", callback_data=f"cancelar|{id_evento}")])
    else:
        tipo_agape = extrair_tipo_agape(evento.get("Ágape", ""))
        if tipo_agape == "gratuito":
            botoes.append([InlineKeyboardButton("🍽 Confirmar com ágape (gratuito)", callback_data=f"confirmar|{id_evento}|gratuito")])
            botoes.append([InlineKeyboardButton("🚫 Confirmar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
        elif tipo_agape == "pago":
            botoes.append([InlineKeyboardButton("🍽 Confirmar com ágape (pago)", callback_data=f"confirmar|{id_evento}|pago")])
            botoes.append([InlineKeyboardButton("🚫 Confirmar sem ágape", callback_data=f"confirmar|{id_evento}|sem")])
        else:
            botoes.append([InlineKeyboardButton("✅ Confirmar presença", callback_data=f"confirmar|{id_evento}|sem")])

    botoes.append([InlineKeyboardButton("🔒 Fechar", callback_data="fechar_mensagem")])
    teclado = InlineKeyboardMarkup(botoes)

    await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)

async def fechar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fecha (apaga) uma mensagem temporária."""
    query = update.callback_query
    await query.answer()
    try:
        await query.delete_message()
    except:
        await query.edit_message_text("Mensagem fechada.")

async def minhas_confirmacoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra lista de eventos que o usuário confirmou."""
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

    texto = "Você tem presença confirmada em:\n\n"
    botoes = []
    for idx, evento in enumerate(confirmados):
        data = evento.get("Data do evento", "")
        nome = evento.get("Nome da loja", "")
        numero = evento.get("Número da loja", "")
        potencia = evento.get("Potência", "")
        horario = evento.get("Hora", "")
        id_evento = f"{data} — {nome}"
        texto += f"{idx+1}. 📅 {data} - {nome} {numero} - {potencia} - {horario}\n"
        botoes.append([InlineKeyboardButton(f"❌ Cancelar {idx+1}", callback_data=f"cancelar|{id_evento}")])

    botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="menu_principal")])
    await query.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

async def iniciar_confirmacao_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa a confirmação de presença."""
    query = update.callback_query
    await query.answer()

    # Formato esperado: confirmar|25/12/2026 — Natalina|gratuito
    partes = query.data.split("|")
    if len(partes) != 3:
        await query.edit_message_text("Erro: dados de confirmação inválidos.")
        return ConversationHandler.END

    _, id_evento, tipo_agape = partes

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
        # Armazenar para depois do cadastro
        context.user_data["pos_cadastro"] = {
            "acao": "confirmar",
            "id_evento": id_evento,
            "tipo_agape": tipo_agape
        }
        if update.effective_chat.type in ["group", "supergroup"]:
            await query.edit_message_text("🔔 Você precisa se cadastrar primeiro! Verifique suas mensagens privadas.")
        await context.bot.send_message(
            chat_id=user_id,
            text="Olá! Antes de confirmar sua presença, preciso fazer seu cadastro. Por favor, envie /start no privado."
        )
        return ConversationHandler.END

    ja_confirmou = buscar_confirmacao(id_evento, user_id)
    if ja_confirmou:
        await query.edit_message_text("Você já confirmou presença para este evento.")
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
        [InlineKeyboardButton("❌ Cancelar presença", callback_data=f"cancelar|{id_evento}")],
        [InlineKeyboardButton("👥 Ver eventos", callback_data="ver_eventos")]
    ])

    await context.bot.send_message(
        chat_id=user_id,
        text=resposta,
        parse_mode="Markdown",
        reply_markup=botoes_privado
    )

    if update.effective_chat.type in ["group", "supergroup"]:
        await query.edit_message_text("✅ Presença confirmada! Verifique seu privado para detalhes.")
    else:
        await query.edit_message_text("✅ Presença confirmada! Verifique a mensagem acima.")

    return ConversationHandler.END

async def cancelar_presenca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela presença de um usuário em um evento."""
    query = update.callback_query
    await query.answer()

    # Formato: cancelar|25/12/2026 — Natalina
    partes = query.data.split("|")
    if len(partes) != 2:
        await query.edit_message_text("Erro: dados de cancelamento inválidos.")
        return
    _, id_evento = partes

    user_id = update.effective_user.id

    # Se veio de um grupo e não é confirmação, pedir confirmação no privado
    if update.effective_chat.type in ["group", "supergroup"] and not query.data.startswith("confirma_cancelar"):
        botoes = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sim, cancelar", callback_data=f"confirma_cancelar|{id_evento}")],
            [InlineKeyboardButton("🔙 Não, voltar", callback_data="voltar_grupo")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Confirmar cancelamento da sessão {id_evento}?",
            reply_markup=botoes
        )
        await query.edit_message_text("Instruções enviadas no privado.")
        return

    cancelou = cancelar_confirmacao(id_evento, user_id)
    if cancelou:
        await query.edit_message_text(
            f"❌ Presença cancelada.\n\n"
            f"Evento: {id_evento}\n\n"
            f"Se mudar de ideia, basta confirmar novamente. Fraterno abraço! 🐐"
        )
    else:
        await query.edit_message_text("Não foi possível cancelar. Você não estava confirmado para este evento.")

# ConversationHandler para confirmação de presença
confirmacao_presenca_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(iniciar_confirmacao_presenca, pattern="^confirmar\\|")],
    states={},
    fallbacks=[CommandHandler("cancelar", cancelar_presenca)],
)